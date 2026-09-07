from __future__ import annotations

from datetime import datetime
from threading import Lock

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.contracts.common import require_aware, require_identifier, utc_instant
from app.domain.goals import GoalStatus

from .bounds import validate_plan_bounds, validate_planning_context_bounds
from .contracts import (
    _PLAN_PROOF,
    ActivityPlan,
    GoalPlanningCandidate,
    GoalPlanningCommitState,
    GoalPlanningContextSnapshot,
    GoalPlanningOutcome,
    _validate_refs,
)


class GoalPlanningAuthority:
    def __init__(self) -> None:
        self._plans: dict[str, ActivityPlan] = {}
        self._current_plans: dict[str, str] = {}
        self._lock = Lock()

    def commit(
        self,
        candidate: GoalPlanningCandidate,
        snapshot: GoalPlanningContextSnapshot,
        current: GoalPlanningCommitState,
        *,
        plan_id: str,
        committed_at: datetime,
        bounds_policy: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    ) -> ActivityPlan:
        if not isinstance(candidate, GoalPlanningCandidate):
            raise ValueError("candidate must be GoalPlanningCandidate")
        if not isinstance(snapshot, GoalPlanningContextSnapshot):
            raise ValueError("snapshot must be GoalPlanningContextSnapshot")
        if not isinstance(current, GoalPlanningCommitState):
            raise ValueError("current must be GoalPlanningCommitState")
        validate_planning_context_bounds(snapshot, bounds_policy)
        validate_plan_bounds(candidate, bounds_policy)
        require_identifier(plan_id, "plan_id")
        require_aware(committed_at, "committed_at")
        if candidate.goal_id != snapshot.goal.goal_id:
            raise ValueError("candidate goal does not match snapshot")
        if candidate.goal_state_revision != snapshot.goal.revision:
            raise ValueError("candidate goal state revision does not match snapshot")
        if candidate.source_event_ids != snapshot.source_event_ids:
            raise ValueError("candidate source events do not match snapshot")
        if candidate.revisions != snapshot.revisions:
            raise ValueError("candidate revisions do not match snapshot")
        if current.revisions != snapshot.revisions:
            raise ValueError("goal planning candidate is stale")
        if current.goal != snapshot.goal or current.goal.status is not GoalStatus.ACTIVE:
            raise ValueError("target goal changed while planning")
        if utc_instant(candidate.created_at) < utc_instant(snapshot.captured_at):
            raise ValueError("candidate cannot predate snapshot")
        _validate_refs(candidate, snapshot)
        directive = snapshot.deterministic_directive
        if directive is not None:
            validate_plan_bounds(directive, bounds_policy)
            if (
                candidate.outcome is not directive.outcome
                or candidate.steps != directive.steps
                or candidate.completion_condition_refs != directive.completion_condition_refs
                or candidate.checkpoint_step_ids != directive.checkpoint_step_ids
                or candidate.failure_policy is not directive.failure_policy
                or candidate.unmet_capabilities != directive.unmet_capabilities
                or candidate.impossibility_blocker_ids != directive.impossibility_blocker_ids
            ):
                raise ValueError("candidate does not match deterministic directive")
        elif candidate.outcome is GoalPlanningOutcome.NO_PLAN_REQUIRED:
            raise ValueError("no-plan outcome requires trusted deterministic directive")
        self._validate_current_capabilities(candidate, snapshot, current)
        self._validate_current_blockers(candidate, snapshot, current)
        previous = snapshot.previous_plan
        if current.previous_plan != previous:
            raise ValueError("再計画の置換対象が判断中に変更されています")
        if previous is not None and utc_instant(snapshot.captured_at) < utc_instant(
            previous.committed_at
        ):
            raise ValueError("置換対象の確定より前の文脈で再計画できません")
        with self._lock:
            if plan_id in self._plans:
                raise ValueError("plan id is already committed")
            current_id = self._current_plans.get(candidate.goal_id)
            if previous is None:
                if current_id is not None:
                    raise ValueError("既存計画の置換対象を明示する必要があります")
            elif current_id != previous.plan_id or self._plans.get(previous.plan_id) != previous:
                raise ValueError("置換対象が現在の登録済み計画と一致しません")
            plan = ActivityPlan(
                plan_id,
                candidate,
                committed_at,
                _proof=_PLAN_PROOF,
                supersedes_plan_id=None if previous is None else previous.plan_id,
            )
            self._plans[plan_id] = plan
            self._current_plans[candidate.goal_id] = plan_id
            return plan

    def snapshot(self, plan_id: str) -> ActivityPlan | None:
        with self._lock:
            return self._plans.get(plan_id)

    def current_plan(self, goal_id: str) -> ActivityPlan | None:
        """目標の現在計画を返し、過去の確定計画と区別する。"""
        require_identifier(goal_id, "goal_id")
        with self._lock:
            plan_id = self._current_plans.get(goal_id)
            return None if plan_id is None else self._plans[plan_id]

    @staticmethod
    def _validate_current_capabilities(
        candidate: GoalPlanningCandidate,
        snapshot: GoalPlanningContextSnapshot,
        current: GoalPlanningCommitState,
    ) -> None:
        initial = {item.capability_id: item for item in snapshot.capabilities}
        live = {item.capability_id: item for item in current.capabilities}
        for step in candidate.steps:
            matching = [
                item
                for item in snapshot.capabilities
                if item.capability_type == step.activity_type
                and step.operation_ref in item.operations
                and all(item.satisfies(requirement) for requirement in step.required_capabilities)
            ]
            if not matching or not any(
                descriptor.capability_id in live
                and live[descriptor.capability_id] == initial[descriptor.capability_id]
                and all(
                    live[descriptor.capability_id].satisfies(requirement)
                    for requirement in step.required_capabilities
                )
                for descriptor in matching
            ):
                raise ValueError("required capability changed while planning")
        for requirement in candidate.unmet_capabilities:
            if any(item.satisfies(requirement) for item in current.capabilities):
                raise ValueError("unmet capability became available while planning")

    @staticmethod
    def _validate_current_blockers(
        candidate: GoalPlanningCandidate,
        snapshot: GoalPlanningContextSnapshot,
        current: GoalPlanningCommitState,
    ) -> None:
        initial = {item.blocker_id: item for item in snapshot.planning_blockers}
        live = {item.blocker_id: item for item in current.planning_blockers}
        for blocker_id in candidate.impossibility_blocker_ids:
            if blocker_id not in initial or live.get(blocker_id) != initial[blocker_id]:
                raise ValueError("planning blocker changed while planning")
