from __future__ import annotations

from datetime import datetime
from threading import Lock

from app.domain.contracts.common import require_aware, require_identifier, utc_instant

from .contracts import (
    _PLAN_PROOF,
    BodyMotionPlan,
    BodyMotionPlanCandidate,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    BodySpatialTargetKind,
)


class BodyMotionPlanAuthority:
    def __init__(self) -> None:
        self._plans: dict[str, BodyMotionPlan] = {}
        self._intent_ids: set[str] = set()
        self._lock = Lock()

    def commit(
        self,
        candidate: BodyMotionPlanCandidate,
        snapshot: BodyMotionPlanningContextSnapshot,
        current: BodyMotionPlanningCommitState,
        *,
        plan_id: str,
        committed_at: datetime,
    ) -> BodyMotionPlan:
        if not isinstance(candidate, BodyMotionPlanCandidate):
            raise ValueError("candidate が不正です")
        if not isinstance(snapshot, BodyMotionPlanningContextSnapshot):
            raise ValueError("snapshot が不正です")
        if not isinstance(current, BodyMotionPlanningCommitState):
            raise ValueError("current state が不正です")
        require_identifier(plan_id, "plan_id")
        require_aware(committed_at, "committed_at")
        self._validate_candidate(candidate, snapshot)
        self._validate_current(snapshot, current)
        if utc_instant(candidate.created_at) < utc_instant(snapshot.captured_at):
            raise ValueError("candidate はsnapshotより古くできません")
        body_model_fingerprint = snapshot.body_model.body_model_fingerprint
        if body_model_fingerprint is None:
            raise ValueError("body model fingerprint がありません")
        with self._lock:
            if plan_id in self._plans or candidate.source_intent_id in self._intent_ids:
                raise ValueError("plan は既にcommit済みです")
            plan = BodyMotionPlan(
                plan_id=plan_id,
                candidate=candidate,
                motion_goal_ref=snapshot.intent.motion_goal_ref,
                priority=snapshot.intent.priority,
                interruptibility=snapshot.intent.interruptibility,
                preconditions=snapshot.intent.preconditions,
                required_capabilities=snapshot.intent.required_capabilities,
                body_model_id=snapshot.body_model.body_model_id,
                body_model_revision=snapshot.body_model.body_model_revision,
                body_model_fingerprint=body_model_fingerprint,
                committed_at=committed_at,
                _proof=_PLAN_PROOF,
            )
            self._plans[plan_id] = plan
            self._intent_ids.add(candidate.source_intent_id)
            return plan

    @staticmethod
    def _validate_candidate(
        candidate: BodyMotionPlanCandidate,
        snapshot: BodyMotionPlanningContextSnapshot,
    ) -> None:
        if (
            candidate.request_id != snapshot.request_id
            or candidate.source_decision_id != snapshot.intent.decision_id
            or candidate.source_intent_id != snapshot.intent.intent_id
            or candidate.revisions != snapshot.intent.revisions
            or candidate.body_model_id != snapshot.body_model.body_model_id
            or candidate.planning_body_state_revision != snapshot.body_state.revision
            or candidate.planning_expression_revision != snapshot.expression.revision
            or candidate.planning_constraints != snapshot.constraints
        ):
            raise ValueError("candidate provenance がsnapshotと一致しません")
        constraint_ids = {item.constraint_id for item in snapshot.constraints}
        if any(set(goal.constraint_refs) - constraint_ids for goal in candidate.goals):
            raise ValueError("candidate constraint ref が不正です")
        for goal in candidate.goals:
            if (
                goal.spatial_target is not None
                and goal.spatial_target.kind is BodySpatialTargetKind.TARGET_REF
                and goal.spatial_target.target_ref != snapshot.intent.target_ref
            ):
                raise ValueError("target はExecutive targetと一致しなければなりません")
        _validate_model_grounding(candidate, snapshot)

    @staticmethod
    def _validate_current(
        snapshot: BodyMotionPlanningContextSnapshot,
        current: BodyMotionPlanningCommitState,
    ) -> None:
        if current.revisions != snapshot.intent.revisions:
            raise ValueError("planning source revisions がstaleです")
        if current.active_intent != snapshot.intent:
            raise ValueError("BODY intent はsuperseded又はchangedです")
        if current.body_model != snapshot.body_model:
            raise ValueError("body model がchangedです")
        if current.constraints != snapshot.constraints:
            raise ValueError("constraint はchangedです")
        if current.capabilities != snapshot.capabilities:
            raise ValueError("capability はchangedです")
        required = {item.precondition_id: item for item in snapshot.intent.preconditions}
        if {item.precondition_id: item for item in current.preconditions} != required:
            raise ValueError("precondition はchangedです")
        captured = {item.capability_id: item for item in current.capabilities}
        if not all(
            any(item.satisfies(requirement) for item in captured.values())
            for requirement in snapshot.intent.required_capabilities
        ):
            raise ValueError("required capability はchanged又はunavailableです")

    def snapshot(self, plan_id: str) -> BodyMotionPlan | None:
        with self._lock:
            return self._plans.get(plan_id)


def _validate_model_grounding(
    candidate: BodyMotionPlanCandidate,
    snapshot: BodyMotionPlanningContextSnapshot,
) -> None:
    model = snapshot.body_model
    chains = {item.chain_id: item for item in model.kinematic_chains}
    end_effectors = set(model.end_effector_joint_ids)
    joints = {item.joint_id: item for item in model.joints}
    for goal in candidate.goals:
        selector = goal.selector
        selected_chain_ids = set(selector.chain_ids)
        selected_end_effector_joint_ids = set(selector.end_effector_joint_ids)
        if (
            selected_chain_ids - set(chains)
            or selected_end_effector_joint_ids - end_effectors
        ):
            raise ValueError("selector がCanonical Body Modelへgroundされていません")
        chain_terminal_joint_ids = {
            chains[chain_id].end_effector_joint_id for chain_id in selected_chain_ids
        }
        if selected_chain_ids and selected_end_effector_joint_ids:
            if selected_end_effector_joint_ids != chain_terminal_joint_ids:
                raise ValueError("chain/end-effector関係が不正です")
        selected_joint_ids = {
            joint_id
            for chain_id in selected_chain_ids
            for joint_id in chains[chain_id].joint_ids
        } | selected_end_effector_joint_ids
        grounding_joint_ids = selected_joint_ids or set(joints)
        if (selector.region is not None or selector.side is not None) and not any(
            (selector.region is None or joints[joint_id].region is selector.region)
            and (selector.side is None or joints[joint_id].side is selector.side)
            for joint_id in grounding_joint_ids
        ):
            raise ValueError("selector region/side がCanonical Body Modelと一致しません")
