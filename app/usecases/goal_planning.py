"""目標計画のLLM呼出しとOwnerの現在性確認を調停する。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.goal_planning.authority import GoalPlanningAuthority
from app.domain.goal_planning.bounds import (
    GoalPlanningBoundsPolicyPort,
    assert_planning_policy_generation,
    validate_planning_context_bounds,
)
from app.domain.goal_planning.contracts import (
    ActivityPlan,
    GoalPlanningCommitState,
    GoalPlanningContextSnapshot,
)
from app.domain.goal_planning.planner import (
    GoalPlanningPolicy,
    build_request,
    candidate_from_directive,
    commit_result,
)
from app.usecases.ports.llm import LLMRolePort


class GoalPlanningLiveStatePort(Protocol):
    async def current_state(
        self, snapshot: GoalPlanningContextSnapshot
    ) -> GoalPlanningCommitState: ...



class GoalPlanner:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: GoalPlanningLiveStatePort,
        authority: GoalPlanningAuthority,
        policy: GoalPlanningPolicy,
        bounds_policy_state: GoalPlanningBoundsPolicyPort | None = None,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._authority = authority
        self._policy = policy
        self._bounds_policy_state = bounds_policy_state

    async def _validate_current_policy(self, snapshot: GoalPlanningContextSnapshot) -> None:
        if self._bounds_policy_state is None:
            return
        current_policy = await self._bounds_policy_state.current_policy(snapshot)
        assert_planning_policy_generation(snapshot, current_policy)

    async def plan(
        self,
        snapshot: GoalPlanningContextSnapshot,
        *,
        request_id: str,
        trace_id: str,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> ActivityPlan:
        validate_planning_context_bounds(snapshot, self._policy.bounds_policy)
        directive = snapshot.deterministic_directive
        if directive is not None:
            candidate = candidate_from_directive(
                snapshot,
                directive,
                candidate_id=candidate_id,
                created_at=created_at,
                bounds_policy=self._policy.bounds_policy,
            )
            current = await self._live_state.current_state(snapshot)
            await self._validate_current_policy(snapshot)
            return self._authority.commit(
                candidate,
                snapshot,
                current,
                plan_id=plan_id,
                committed_at=created_at,
                bounds_policy=self._policy.bounds_policy,
            )
        request = build_request(
            snapshot,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)
        current = await self._live_state.current_state(snapshot)
        await self._validate_current_policy(snapshot)
        return commit_result(
            request,
            result,
            snapshot=snapshot,
            current=current,
            authority=self._authority,
            plan_id=plan_id,
            policy=self._policy,
        )

