"""深い主観評価のLLM呼出しと現在性確認を調停するユースケース。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.appraisal.contracts import AppraisalCandidate, InternalStateSnapshot
from app.domain.appraisal.deep import (
    DeepAppraisalContext,
    DeepAppraisalFreshnessStamp,
    DeepAppraisalPolicy,
    build_deep_request,
    commit_deep_result,
)
from app.domain.contracts import EventEnvelope
from app.domain.input_meaning import StructuredInputMeaning
from app.usecases.ports.llm import LLMRolePort


class DeepAppraisalLiveStatePort(Protocol):
    """source contextとInternal Stateの一貫したread-only freshness境界。"""

    async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp: ...



class DeepAppraisalInterpreter:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: DeepAppraisalLiveStatePort,
        policy: DeepAppraisalPolicy,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._policy = policy

    async def appraise(
        self,
        event: EventEnvelope,
        meaning: StructuredInputMeaning | None,
        snapshot: InternalStateSnapshot,
        context: DeepAppraisalContext,
        *,
        request_id: str,
        trace_id: str,
        created_at: datetime,
    ) -> AppraisalCandidate:
        request = build_deep_request(
            event,
            meaning,
            snapshot,
            context,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)
        freshness = await self._live_state.freshness_stamp()
        return commit_deep_result(
            request,
            result,
            event=event,
            snapshot=snapshot,
            context=context,
            current_source_context_revision=freshness.source_context_revision,
            current_state_revision=freshness.state_revision,
            policy=self._policy,
        )

