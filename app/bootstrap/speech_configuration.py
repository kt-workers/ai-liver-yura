"""Speechの明示構成を既存Brain laneと終了処理へ登録する。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.bootstrap.speech_semantics_policy import ExecutiveSpeechPolicyEvidence
from app.domain.brain_integration import BrainIntegrationModule
from app.domain.speech_runtime.shutdown import SpeechRuntimeShutdown
from app.usecases.brain_integration_runtime import BrainIntegrationWork
from app.usecases.input_reference_context_facade import CoreInputReferenceContextBinding
from app.usecases.speech_delivery import CoreSpeechDelivery
from app.usecases.speech_pipeline import CoreSpeechPipeline

if TYPE_CHECKING:
    from app.usecases.cognition_delivery import CoreCognitionDelivery


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
        if cognition.reflection is not None:
            reflection = cognition.reflection
            pipeline.reflection_observer = lambda work, record: reflection.observe_presentation(
                work.envelope, record
            )
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
