"""Speechの明示構成を既存Brain laneと終了処理へ登録する。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.speech import CoreSpeechPipeline
from app.composition.speech_semantics_policy import ExecutiveSpeechPolicyEvidence
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationWork,
)
from app.domain.executive import CommittedExecutiveDecision, ExecutiveIntentKind
from app.domain.speech_runtime.discard import PreparedAudioDiscardReason
from app.domain.speech_runtime.shutdown import SpeechRuntimeShutdown
from app.runtime.kernel import CancellationToken

if TYPE_CHECKING:
    from app.composition.cognition import CoreCognitionDelivery


@dataclass(frozen=True, slots=True)
class _SpeechWork:
    decision: CommittedExecutiveDecision
    intent_id: str


class CoreSpeechDelivery:
    def __init__(
        self,
        cognition: CoreCognitionDelivery,
        pipeline: CoreSpeechPipeline,
        shutdown: SpeechRuntimeShutdown,
    ) -> None:
        self.cognition, self.pipeline, self.shutdown = cognition, pipeline, shutdown

    async def close(self) -> None:
        # Session回収前に既存Ownerを取消へ進め、close時にterminal Factを投影する。
        try:
            for candidate_id in await self.pipeline.runtime.active_candidate_ids():
                await self.pipeline.discarder.discard_current(
                    candidate_id,
                    self.pipeline.runtime.generation(candidate_id),
                    PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
                )
                try:
                    await self.pipeline.runtime.cancel(candidate_id)
                except ValueError:
                    # discardのawait中に終端reportが受理された場合は既存終端を保つ。
                    if candidate_id in await self.pipeline.runtime.active_candidate_ids():
                        raise
        finally:
            await self.shutdown.close()

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        # sourceの厳密なcurrentnessは#677 Builderと各Ownerが検査する。
        return isinstance(work.payload, _SpeechWork)

    async def execute(self, work: BrainIntegrationWork, cancellation: CancellationToken) -> object:
        if not isinstance(work.payload, _SpeechWork):
            raise ValueError("Speech配送の型が不正です")
        return await self.pipeline.execute(
            work, work.payload.decision, work.payload.intent_id, cancellation
        )

    def accept_decision(self, work: BrainIntegrationWork, result: object) -> None:
        if not isinstance(result, CommittedExecutiveDecision):
            raise ValueError("Speech配送には確定Executive判断が必要です")
        for intent in result.candidate.intents:
            if intent.kind is not ExecutiveIntentKind.SPEECH:
                continue
            child = BrainIntegrationWork(
                result.decision_id + ":" + intent.intent_id + ":speech-work",
                BrainIntegrationModule.SPEECH_SEMANTICS,
                BrainIntegrationLane.SPEECH_PREPARATION,
                replace(work.envelope, source_event_ids=result.candidate.source_event_ids),
                _SpeechWork(result, intent.intent_id),
                deadline_at=work.deadline_at,
            )
            if not self.cognition.brain.submit(child).accepted:
                raise ValueError("Speech preparationをBrain Runtimeが受付しませんでした")


@dataclass(frozen=True, slots=True)
class CoreSpeechConfiguration:
    """各Ownerとcontext読取を組み立てる構成関数を明示登録する。"""

    evidence: ExecutiveSpeechPolicyEvidence
    build: Callable[
        [CoreCognitionDelivery, CoreInputReferenceContextBinding],
        tuple[CoreSpeechPipeline, SpeechRuntimeShutdown],
    ]

    def compose(
        self, cognition: CoreCognitionDelivery, reference: CoreInputReferenceContextBinding
    ) -> CoreSpeechDelivery:
        pipeline, shutdown = self.build(cognition, reference)
        delivery = CoreSpeechDelivery(cognition, pipeline, shutdown)
        cognition.brain.register_module(BrainIntegrationModule.SPEECH_SEMANTICS, delivery)
        previous = cognition._decision_delivery

        def forward(work: BrainIntegrationWork, result: object) -> None:
            if previous is not None:
                previous(work, result)
            delivery.accept_decision(work, result)

        cognition._decision_delivery = forward
        cognition.speech = delivery
        return delivery
