"""身体運動計画のOwner現在性確認とLLM・決定論的要求を調停する。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.body_motion_planning.authority import BodyMotionPlanAuthority
from app.domain.body_motion_planning.contracts import (
    BodyMotionPlan,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
)
from app.domain.body_motion_planning.planner import (
    BodyMotionPlanningPolicy,
    build_request,
    candidate_from_directive,
    descriptor,
    parse_candidate,
)
from app.domain.llm import LLMRoleStatus, validate_role_exchange
from app.usecases.ports.llm import LLMRolePort


class BodyMotionPlanningLiveStatePort(Protocol):
    async def current_commit_state(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
    ) -> BodyMotionPlanningCommitState: ...



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
