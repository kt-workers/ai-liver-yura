"""Executive判断をBrain Runtimeの型付きworkとして受け付ける。"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.brain_integration import BrainIntegrationModule
from app.domain.contracts.common import require_identifier
from app.domain.executive import CommittedExecutiveDecision
from app.runtime.kernel import CancellationToken
from app.usecases.attention_binding import CoreAttentionDispatch
from app.usecases.brain_integration_runtime import BrainIntegrationWork
from app.usecases.executive_binding import CoreExecutiveBinding, _validate_envelope


@dataclass(frozen=True, slots=True)
class ExecutiveBrainWorkPayload:
    dispatch: CoreAttentionDispatch
    request_id: str
    decision_id: str

class ExecutiveBrainModulePort:
    """既存本体実行の有界な受付と取消・停止へ判断を登録する。"""

    def __init__(self, binding: CoreExecutiveBinding) -> None:
        self._binding = binding

    @staticmethod
    def _validate(work: BrainIntegrationWork) -> ExecutiveBrainWorkPayload:
        payload = work.payload
        if work.module is not BrainIntegrationModule.EXECUTIVE or not isinstance(
            payload, ExecutiveBrainWorkPayload
        ):
            raise ValueError("判断処理の構成入力が不正です")
        require_identifier(payload.request_id, "request_id")
        require_identifier(payload.decision_id, "decision_id")
        _validate_envelope(payload.dispatch, work.envelope)
        return payload

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        payload = self._validate(work)
        return self._binding.is_current(payload.dispatch)

    async def execute(
        self, work: BrainIntegrationWork, cancellation: CancellationToken
    ) -> CommittedExecutiveDecision:
        payload = self._validate(work)
        return await self._binding.deliberate(
            payload.dispatch,
            request_id=payload.request_id,
            trace_id=work.envelope.trace_id,
            decision_id=payload.decision_id,
            cancellation=cancellation,
            envelope=work.envelope,
        )
