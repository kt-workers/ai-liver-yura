"""生成済み発話に対応する音声合成要求を公開契約で構築する。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.adapters.tts import (
    PreparedAudioResourceStore,
    PronunciationOverrideView,
    TTSCapabilityView,
    TTSPerformanceMappingPolicy,
    TTSProviderOperationalPolicy,
    TTSSynthesisPriority,
    TTSSynthesisRequest,
    TTSVoiceBinding,
)
from app.adapters.tts.provider import TTSProviderClient
from app.domain.character_language import CharacterUtterance
from app.domain.contracts.common import JsonValue
from app.domain.speech_performance import SpeechPerformancePlan
from app.domain.speech_runtime.presentation import PresentationAdapter
from app.runtime.lifecycle import DependencyRetryPolicy

from .tts import _project


@dataclass(frozen=True)
class GeneratedAudioSettings:
    voice: TTSVoiceBinding
    capability: TTSCapabilityView
    overrides: tuple[PronunciationOverrideView, ...]
    provider_config_revision: int
    pronunciation_config_revision: int
    priority: TTSSynthesisPriority
    mapping: TTSPerformanceMappingPolicy
    operational: TTSProviderOperationalPolicy
    retry: DependencyRetryPolicy

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", tuple(self.overrides))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "voice": self.voice,
                "capability": self.capability,
                "overrides": self.overrides,
                "provider_config_revision": self.provider_config_revision,
                "pronunciation_config_revision": self.pronunciation_config_revision,
                "priority": self.priority,
                "mapping": self.mapping,
                "operational": self.operational,
                "retry": self.retry,
            }
        )

    def request(
        self,
        candidate_id: str,
        utterance: CharacterUtterance,
        performance: SpeechPerformancePlan,
        now: datetime,
    ) -> TTSSynthesisRequest:
        return TTSSynthesisRequest(
            f"{candidate_id}:tts",
            candidate_id,
            utterance,
            performance,
            self.voice,
            self.capability,
            self.overrides,
            self.provider_config_revision,
            self.pronunciation_config_revision,
            self.mapping.mapping_id,
            self.mapping.mapping_revision,
            self.retry.policy_id,
            self.retry.policy_revision,
            self.priority,
            now,
            candidate_id,
        )


@dataclass(frozen=True)
class GeneratedAudioBindings:
    client: TTSProviderClient
    presentation: Callable[[PreparedAudioResourceStore], PresentationAdapter]
