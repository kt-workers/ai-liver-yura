from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from app.domain.body import AnatomicalRegion, AnatomicalSide, Vector3
from app.domain.body_expression import BodyExpressionAxis
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import JsonValue, require_aware
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMPriority,
    LLMRoleDescriptor,
    LLMRoleRequest,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
    validate_role_exchange,
)
from app.usecases.ports.llm import LLMRolePort

from .authority import BodyMotionPlanAuthority
from .contracts import (
    BodyBalanceMode,
    BodyCoordinationConstraint,
    BodyCoordinationMode,
    BodyExpressionBinding,
    BodyMotionConstraintKind,
    BodyMotionConstraintView,
    BodyMotionEffect,
    BodyMotionGoal,
    BodyMotionPhase,
    BodyMotionPlan,
    BodyMotionPlanCandidate,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    BodyMotionSelector,
    BodySpatialTarget,
    BodySpatialTargetKind,
    DeterministicBodyPlanningDirective,
)

ROLE_ID = "body_motion_planning"
INPUT_SCHEMA = "body.motion-planning.context.v1"
OUTPUT_SCHEMA = "body.motion-planning.candidate.v1"


@dataclass(frozen=True, slots=True)
class BodyMotionPlanningPolicy:
    execution: LLMExecutionPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.execution, LLMExecutionPolicy):
            raise ValueError("execution が不正です")


class BodyMotionPlanningLiveStatePort(Protocol):
    async def current_commit_state(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
    ) -> BodyMotionPlanningCommitState: ...


def descriptor(policy: BodyMotionPlanningPolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        ROLE_ID,
        "Executive確定BODY intentから高レベル身体運動candidateを構成する",
        INPUT_SCHEMA,
        OUTPUT_SCHEMA,
        "body_motion_plan_candidate_only",
        LLMActivationPolicy.CONDITIONAL,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.execution,
    )


def build_request(
    snapshot: BodyMotionPlanningContextSnapshot,
    *,
    trace_id: str,
    created_at: datetime,
    policy: BodyMotionPlanningPolicy,
) -> LLMRoleRequest:
    if not isinstance(snapshot, BodyMotionPlanningContextSnapshot):
        raise ValueError("snapshot が不正です")
    require_aware(created_at, "created_at")
    payload = {
        "request_id": snapshot.request_id,
        "intent": {
            "decision_id": snapshot.intent.decision_id,
            "intent_id": snapshot.intent.intent_id,
            "purpose": snapshot.intent.purpose,
            "motion_goal_ref": snapshot.intent.motion_goal_ref,
            "target_ref": snapshot.intent.target_ref,
            "constraint_refs": list(snapshot.intent.constraint_refs),
            "revisions": snapshot.intent.revisions.to_dict(),
        },
        "body_model": snapshot.body_model.to_dict(),
        "body_state": snapshot.body_state.to_dict(),
        "expression": {
            "revision": snapshot.expression.revision,
            "capture_source_context_revision": snapshot.expression.capture_source_context_revision,
            "internal_state_revision": snapshot.expression.internal_state_revision,
            "attention_revision": snapshot.expression.attention_revision,
            "character_id": snapshot.expression.character_id,
            "character_definition_revision": snapshot.expression.character_definition_revision,
            "projection_policy_id": snapshot.expression.projection_policy_id,
            "projection_policy_revision": snapshot.expression.projection_policy_revision,
            "axes": [
                {"axis": item.axis.value, "value": item.value.value}
                for item in snapshot.expression.axes
            ],
            "focus": {
                "foreground_focus_ref": snapshot.expression.focus_constraint.foreground_focus_ref,
                "active_focus_intent_ref": (
                    snapshot.expression.focus_constraint.active_focus_intent_ref
                ),
                "secondary_monitor_refs": list(
                    snapshot.expression.focus_constraint.secondary_monitor_refs
                ),
                "current_turn_owner": snapshot.expression.focus_constraint.current_turn_owner,
                "response_obligation": snapshot.expression.focus_constraint.response_obligation,
            },
        },
        "constraints": [
            {
                "constraint_id": item.constraint_id,
                "kind": item.kind.value,
                "source_owner": item.source_owner,
                "source_ref": item.source_ref,
                "source_revision": item.source_revision,
                "semantic_description": item.semantic_description,
                "subject_refs": list(item.subject_refs),
            }
            for item in snapshot.constraints
        ],
        "capabilities": [item.to_dict() for item in snapshot.capabilities],
    }
    return LLMRoleRequest(
        snapshot.request_id,
        ROLE_ID,
        StructuredPayload(INPUT_SCHEMA, cast(JsonValue, payload)),
        snapshot.intent.source_event_ids,
        snapshot.intent.revisions,
        snapshot.intent.preconditions,
        {
            "foreground": LLMPriority.FOREGROUND,
            "normal": LLMPriority.NORMAL,
            "background": LLMPriority.BACKGROUND,
        }[snapshot.intent.priority.value],
        {
            "interruptible": LLMInterruptibility.INTERRUPTIBLE,
            "soft_cancel_only": LLMInterruptibility.SOFT_CANCEL_ONLY,
            "non_interruptible": LLMInterruptibility.NON_INTERRUPTIBLE,
        }[snapshot.intent.interruptibility.value],
        LLMStalePolicy.REJECT,
        policy.execution,
        created_at,
        trace_id,
    )


def parse_candidate(value: object, *, created_at: datetime) -> BodyMotionPlanCandidate:
    if not isinstance(value, Mapping):
        raise ValueError("candidate はobjectでなければなりません")
    required = {
        "candidate_id",
        "request_id",
        "source_decision_id",
        "source_intent_id",
        "revisions",
        "body_model_id",
        "planning_body_state_revision",
        "planning_expression_revision",
        "planning_constraints",
        "goals",
        "phases",
        "coordination_constraints",
        "expression_bindings",
    }
    if set(value) != required:
        raise ValueError("candidate fields がschemaと一致しません")
    revisions = _exact_mapping(
        value["revisions"],
        "revisions",
        {"source_context_revision", "goal_revision", "attention_revision"},
    )
    candidate = BodyMotionPlanCandidate(
        _string(value["candidate_id"], "candidate_id"),
        _string(value["request_id"], "request_id"),
        _string(value["source_decision_id"], "source_decision_id"),
        _string(value["source_intent_id"], "source_intent_id"),
        RevisionVector(
            _integer(revisions.get("source_context_revision"), "source_context_revision"),
            _integer(revisions.get("goal_revision"), "goal_revision"),
            _integer(revisions.get("attention_revision"), "attention_revision"),
        ),
        _string(value["body_model_id"], "body_model_id"),
        _integer(value["planning_body_state_revision"], "planning_body_state_revision"),
        _integer(value["planning_expression_revision"], "planning_expression_revision"),
        tuple(
            _constraint(item)
            for item in _array(value["planning_constraints"], "planning_constraints")
        ),
        tuple(_goal(item) for item in _array(value["goals"], "goals")),
        tuple(_phase(item) for item in _array(value["phases"], "phases")),
        tuple(
            _coordination(item)
            for item in _array(value["coordination_constraints"], "coordination_constraints")
        ),
        tuple(
            _binding(item) for item in _array(value["expression_bindings"], "expression_bindings")
        ),
        created_at,
    )
    return candidate


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} がobjectではありません")
    return cast(Mapping[str, object], value)


def _exact_mapping(value: object, name: str, fields: set[str]) -> Mapping[str, object]:
    item = _mapping(value, name)
    if set(item) != fields:
        raise ValueError(f"{name} fields がschemaと一致しません")
    return item


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} がarrayではありません")
    return tuple(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} がstringではありません")
    return value


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} がintではありません")
    return value


def _number(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} がnumberではありません")
    assert isinstance(value, (int, float))
    return float(value)


def _strings(value: object, name: str) -> tuple[str, ...]:
    return tuple(_string(item, name) for item in _array(value, name))


def _constraint(value: object) -> BodyMotionConstraintView:
    item = _exact_mapping(
        value,
        "constraint",
        {
            "constraint_id",
            "kind",
            "source_owner",
            "source_ref",
            "source_revision",
            "semantic_description",
            "subject_refs",
        },
    )
    return BodyMotionConstraintView(
        _string(item.get("constraint_id"), "constraint_id"),
        BodyMotionConstraintKind(_string(item.get("kind"), "kind")),
        _string(item.get("source_owner"), "source_owner"),
        _string(item.get("source_ref"), "source_ref"),
        _integer(item.get("source_revision"), "source_revision"),
        _string(item.get("semantic_description"), "semantic_description"),
        _strings(item.get("subject_refs"), "subject_refs"),
    )


def _selector(value: object) -> BodyMotionSelector:
    item = _exact_mapping(
        value,
        "selector",
        {"region", "side", "chain_ids", "end_effector_joint_ids"},
    )
    region = item.get("region")
    side = item.get("side")
    return BodyMotionSelector(
        None if region is None else AnatomicalRegion(_string(region, "region")),
        None if side is None else AnatomicalSide(_string(side, "side")),
        _strings(item.get("chain_ids"), "chain_ids"),
        _strings(item.get("end_effector_joint_ids"), "end_effector_joint_ids"),
    )


def _target(value: object | None) -> BodySpatialTarget | None:
    if value is None:
        return None
    item = _exact_mapping(
        value,
        "spatial_target",
        {"kind", "direction", "target_ref", "extent"},
    )
    direction = item.get("direction")
    vector = None
    if direction is not None:
        direction_map = _exact_mapping(direction, "direction", {"x", "y", "z"})
        vector = Vector3(
            _number(direction_map["x"], "direction.x"),
            _number(direction_map["y"], "direction.y"),
            _number(direction_map["z"], "direction.z"),
        )
    target_ref = item.get("target_ref")
    return BodySpatialTarget(
        BodySpatialTargetKind(_string(item.get("kind"), "kind")),
        vector,
        None if target_ref is None else _string(target_ref, "target_ref"),
        _number(item.get("extent"), "extent"),
    )


def _goal(value: object) -> BodyMotionGoal:
    item = _exact_mapping(
        value,
        "goal",
        {"goal_id", "effect", "selector", "spatial_target", "intensity", "constraint_refs"},
    )
    return BodyMotionGoal(
        _string(item.get("goal_id"), "goal_id"),
        BodyMotionEffect(_string(item.get("effect"), "effect")),
        _selector(item.get("selector")),
        _target(item.get("spatial_target")),
        _number(item.get("intensity"), "intensity"),
        _strings(item.get("constraint_refs"), "constraint_refs"),
    )


def _binding(value: object) -> BodyExpressionBinding:
    item = _exact_mapping(value, "binding", {"binding_id", "axis", "influence"})
    return BodyExpressionBinding(
        _string(item.get("binding_id"), "binding_id"),
        BodyExpressionAxis(_string(item.get("axis"), "axis")),
        _number(item.get("influence"), "influence"),
    )


def _phase(value: object) -> BodyMotionPhase:
    item = _exact_mapping(
        value,
        "phase",
        {
            "phase_id",
            "goal_ids",
            "relative_duration_weight",
            "balance_mode",
            "expression_binding_ids",
        },
    )
    return BodyMotionPhase(
        _string(item.get("phase_id"), "phase_id"),
        _strings(item.get("goal_ids"), "goal_ids"),
        _number(item.get("relative_duration_weight"), "relative_duration_weight"),
        BodyBalanceMode(_string(item.get("balance_mode"), "balance_mode")),
        _strings(item.get("expression_binding_ids"), "expression_binding_ids"),
    )


def _coordination(value: object) -> BodyCoordinationConstraint:
    item = _exact_mapping(
        value,
        "coordination",
        {"coordination_id", "goal_ids", "mode"},
    )
    return BodyCoordinationConstraint(
        _string(item.get("coordination_id"), "coordination_id"),
        _strings(item.get("goal_ids"), "goal_ids"),
        BodyCoordinationMode(_string(item.get("mode"), "mode")),
    )


def candidate_from_directive(
    snapshot: BodyMotionPlanningContextSnapshot,
    directive: DeterministicBodyPlanningDirective,
    *,
    candidate_id: str,
    created_at: datetime,
) -> BodyMotionPlanCandidate:
    if snapshot.deterministic_directive != directive:
        raise ValueError("directive がplanning snapshotと一致しません")
    return BodyMotionPlanCandidate(
        candidate_id,
        snapshot.request_id,
        snapshot.intent.decision_id,
        snapshot.intent.intent_id,
        snapshot.intent.revisions,
        snapshot.body_model.body_model_id,
        snapshot.body_state.revision,
        snapshot.expression.revision,
        snapshot.constraints,
        directive.goals,
        directive.phases,
        directive.coordination_constraints,
        directive.expression_bindings,
        created_at,
    )


class DeterministicBodyMotionPlanner:
    def __init__(
        self,
        live_state: BodyMotionPlanningLiveStatePort,
        authority: BodyMotionPlanAuthority,
    ) -> None:
        self._live_state = live_state
        self._authority = authority

    async def plan(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
        *,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> BodyMotionPlan:
        directive = snapshot.deterministic_directive
        if directive is None:
            raise ValueError("deterministic directive が必要です")
        candidate = candidate_from_directive(
            snapshot,
            directive,
            candidate_id=candidate_id,
            created_at=created_at,
        )
        current = await self._live_state.current_commit_state(snapshot)
        return self._authority.commit(
            candidate,
            snapshot,
            current,
            plan_id=plan_id,
            committed_at=created_at,
        )


class BodyMotionPlanner:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: BodyMotionPlanningLiveStatePort,
        authority: BodyMotionPlanAuthority,
        policy: BodyMotionPlanningPolicy,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._authority = authority
        self._policy = policy

    async def plan(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
        *,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> BodyMotionPlan:
        directive = snapshot.deterministic_directive
        if directive is not None:
            return await DeterministicBodyMotionPlanner(
                self._live_state,
                self._authority,
            ).plan(
                snapshot,
                candidate_id=candidate_id,
                plan_id=plan_id,
                created_at=created_at,
            )
        request = build_request(
            snapshot,
            trace_id=snapshot.trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)
        failure = validate_role_exchange(descriptor(self._policy), request, result)
        if failure is not None or result.status is not LLMRoleStatus.SUCCEEDED:
            raise ValueError("Body Motion LLM result はcommitできません")
        if result.output is None:
            raise ValueError("Body Motion LLM output がありません")
        candidate = parse_candidate(result.output.value, created_at=result.completed_at)
        current = await self._live_state.current_commit_state(snapshot)
        return self._authority.commit(
            candidate,
            snapshot,
            current,
            plan_id=plan_id,
            committed_at=result.completed_at,
        )
