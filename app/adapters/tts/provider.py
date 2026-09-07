from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from .contracts import (
    PreparedAudioArtifact,
    SpeechTimingKind,
    TTSDegradationReason,
    TTSFailureCode,
)


@dataclass(frozen=True, slots=True)
class ProviderPitchAnchor:
    position: float
    relative_pitch: float
    strength: float


@dataclass(frozen=True, slots=True)
class ProviderSegmentParameters:
    utterance_segment_id: str
    boundary_strength: float
    pause_after: float | None
    duration_bias: float
    emphasis_strength: float
    hesitation_strength: float
    local_intent_parameters: tuple[tuple[str, float], ...]
    pitch_anchors: tuple[ProviderPitchAnchor, ...]


@dataclass(frozen=True, slots=True)
class ProviderSynthesisInput:
    global_parameters: tuple[tuple[str, float], ...]
    segments: tuple[ProviderSegmentParameters, ...]


@dataclass(frozen=True, slots=True)
class ProviderTimingUnit:
    unit_id: str
    segment_id: str
    kind: SpeechTimingKind
    symbol: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class TTSProviderResponse:
    raw_audio_ref: str
    audio_format: str
    content_digest: str
    duration_ms: int | None
    timing_units: tuple[ProviderTimingUnit, ...] = ()
    timing_trustworthy: bool = True

    def __post_init__(self) -> None:
        if type(self.timing_trustworthy) is not bool:
            raise ValueError("timing_trustworthy が不正です")
        object.__setattr__(self, "timing_units", tuple(self.timing_units))


class TTSProviderError(Exception):
    """Providerの生エラーを閉じ込めるためのInfrastructure内部例外。"""

    def __init__(self, code: TTSFailureCode, retryable: bool) -> None:
        if not isinstance(code, TTSFailureCode) or type(retryable) is not bool:
            raise ValueError("TTS provider failureが不正です")
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)


class TTSProviderClient(Protocol):
    async def synthesize(
        self,
        voice_ref: str,
        texts: tuple[str, ...],
        provider_input: ProviderSynthesisInput,
    ) -> TTSProviderResponse: ...


@dataclass(slots=True)
class CandidateArtifactStore:
    """#348へ渡す前だけに使う、候補単位の再利用・破棄境界。"""

    _artifacts: dict[str, PreparedAudioArtifact] = field(default_factory=dict)
    _discarded_candidates: set[str] = field(default_factory=set)

    def retain(self, artifact: PreparedAudioArtifact) -> None:
        if artifact.candidate_id not in self._discarded_candidates:
            self._artifacts[artifact.candidate_id] = artifact

    def discard(self, candidate_id: str) -> TTSDegradationReason:
        self._discarded_candidates.add(candidate_id)
        self._artifacts.pop(candidate_id, None)
        return TTSDegradationReason.ARTIFACT_DISCARDED

    def current_artifact(self, candidate_id: str) -> PreparedAudioArtifact | None:
        if candidate_id in self._discarded_candidates:
            return None
        return self._artifacts.get(candidate_id)


class PreparedAudioResourceStore(Protocol):
    """public DTOへprovider refを出さず、#358内だけでsafe handleを解決するPort。"""

    def store(self, artifact_id: str, request_id: str, raw_resource_ref: str) -> str: ...

    def resolve(self, artifact_ref: str) -> str | None: ...


@dataclass(slots=True)
class InMemoryPreparedAudioResourceStore:
    _resources: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    def store(self, artifact_id: str, request_id: str, raw_resource_ref: str) -> str:
        material = f"{artifact_id}\x1f{request_id}\x1f{raw_resource_ref}"
        artifact_ref = f"artifact://prepared/{hashlib.sha256(material.encode('utf-8')).hexdigest()}"
        self._resources[artifact_ref] = (artifact_id, request_id, raw_resource_ref)
        return artifact_ref

    def resolve(self, artifact_ref: str) -> str | None:
        resource = self._resources.get(artifact_ref)
        return None if resource is None else resource[2]
