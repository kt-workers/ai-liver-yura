"""入力意味解析のLLM呼出しと、返却後の現在性確認を調停する。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.input_gateway import NormalizedInputEvent
from app.domain.input_meaning.contracts import (
    InputMeaningBoundaryFailure,
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    ReferenceContext,
)
from app.domain.input_meaning.interpreter import (
    InputMeaningCommitRejected,
    InputMeaningPolicy,
    build_request,
    commit_result,
    descriptor,
)
from app.domain.llm import LLMFailureCode, LLMRoleStatus, validate_role_exchange
from app.usecases.ports.llm import LLMRolePort


class InputMeaningLiveContextPort(Protocol):
    """Input Meaning commit直前の世代付き採用状態を読み取る境界。"""

    async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp: ...


class InputMeaningInterpreter:
    def __init__(
        self,
        port: LLMRolePort,
        live_context: InputMeaningLiveContextPort,
        policy: InputMeaningPolicy,
    ) -> None:
        self._port = port
        self._live_context = live_context
        self._policy = policy

    async def interpret(
        self,
        event: NormalizedInputEvent,
        context: ReferenceContext,
        *,
        request_id: str,
        trace_id: str,
        created_at: datetime,
    ) -> InputMeaningInterpretationResult:
        request = build_request(
            event,
            context,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)

        def reject(
            code: LLMFailureCode, message: str, status: LLMRoleStatus | None
        ) -> InputMeaningInterpretationResult:
            return InputMeaningInterpretationResult(
                request.request_id,
                request.trace_id,
                request.source_event_ids[0],
                request.revisions.source_context_revision,
                status,
                boundary_failure=InputMeaningBoundaryFailure(code, message),
            )

        exchange_failure = validate_role_exchange(descriptor(self._policy), request, result)
        if exchange_failure is not None:
            return reject(exchange_failure.code, "応答の識別または交換契約が不正です", None)
        if result.status is not LLMRoleStatus.SUCCEEDED:
            return InputMeaningInterpretationResult(
                request.request_id,
                request.trace_id,
                request.source_event_ids[0],
                request.revisions.source_context_revision,
                result.status,
                role_failure=result.failure,
            )
        try:
            freshness_stamp = await self._live_context.current_freshness_stamp()
        except Exception:
            # 外部取消はBaseExceptionであり、この運用上の取得失敗には含めない。
            return reject(LLMFailureCode.REJECTED, "現在世代を取得できません", result.status)
        if not isinstance(freshness_stamp, InputMeaningFreshnessStamp):
            return reject(LLMFailureCode.REJECTED, "現在世代を確定できません", result.status)
        try:
            meaning = commit_result(
                request,
                result,
                reference_context=context,
                freshness_stamp=freshness_stamp,
                policy=self._policy,
            )
        except InputMeaningCommitRejected as error:
            return reject(error.code, "入力意味の採用条件を満たしていません", result.status)
        return InputMeaningInterpretationResult(
            request.request_id,
            request.trace_id,
            request.source_event_ids[0],
            request.revisions.source_context_revision,
            result.status,
            meaning=meaning,
        )

