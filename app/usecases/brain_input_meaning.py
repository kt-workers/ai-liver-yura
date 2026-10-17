"""入力意味解析の作業を実行し、採用可能な結果だけを既存所有者へ渡す。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.domain.brain_integration import BrainIntegrationLane, BrainIntegrationModule
from app.domain.input_gateway import InputAdmission, NormalizedInputEvent
from app.domain.input_meaning import (
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    ReferenceContext,
)
from app.usecases.accepted_inputs import CoreAcceptedInputStore
from app.usecases.brain_integration_runtime import BrainIntegrationWork
from app.usecases.input_meaning import InputMeaningInterpreter
from app.usecases.ports.cancellation import CancellationState
from app.usecases.task_cleanup import reap_owned_task


@dataclass(frozen=True, slots=True)
class InputMeaningBrainWorkPayload:
    """既存所有者の入力だけを運び、要求時刻と追跡識別子は重複させない。"""

    event: NormalizedInputEvent
    reference_context: ReferenceContext
    request_id: str
    admission: InputAdmission | None = None


class InputMeaningBrainModulePort:
    """固定入力の自己整合を検査し、意味の採用は既存所有者へ委譲する。"""

    def __init__(
        self, interpreter: InputMeaningInterpreter, inputs: CoreAcceptedInputStore | None = None
    ) -> None:
        self._interpreter = interpreter
        self.inputs = inputs

    @staticmethod
    def _validate(work: BrainIntegrationWork) -> InputMeaningBrainWorkPayload:
        payload = work.payload
        if (
            not isinstance(payload, InputMeaningBrainWorkPayload)
            or not isinstance(payload.event, NormalizedInputEvent)
            or not isinstance(payload.reference_context, ReferenceContext)
            or not isinstance(payload.request_id, str)
            or not payload.request_id.strip()
        ):
            raise ValueError("入力意味解析の構成入力が不正です")
        event = payload.event.envelope
        if (
            work.module is not BrainIntegrationModule.INPUT_MEANING
            or work.lane is not BrainIntegrationLane.FOREGROUND_INTERACTION
            or work.envelope.source_event_ids != (event.event_id,)
            or work.envelope.source_context_revision != event.revisions.source_context_revision
            or work.envelope.source_context_revision
            != payload.reference_context.source_context_revision
            or work.envelope.trace_id != event.trace_id
        ):
            raise ValueError("入力意味解析の構成入力の識別子または世代が一致しません")
        return payload

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        self._validate(work)
        return True

    async def execute(
        self,
        work: BrainIntegrationWork,
        cancellation: CancellationState,
    ) -> InputMeaningInterpretationResult:
        payload = self._validate(work)
        if cancellation.cancelled:
            raise asyncio.CancelledError
        task = asyncio.create_task(
            self._interpreter.interpret(
                payload.event,
                payload.reference_context,
                request_id=payload.request_id,
                trace_id=work.envelope.trace_id,
                created_at=work.envelope.created_at,
            )
        )
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            try:
                await reap_owned_task(task)
            except (asyncio.CancelledError, Exception):
                pass
            raise

        if cancellation.cancelled:
            raise asyncio.CancelledError
        if self.inputs is not None and result.meaning is not None:
            self.inputs.retain(payload.event, result)
        return result


class UnavailableInputMeaningLiveContextPort:
    """未接続の現在世代を捏造せず、既存の取得失敗境界へ通知する。"""

    async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
        raise RuntimeError("現在の入力文脈の権威ある世代は未接続です")
