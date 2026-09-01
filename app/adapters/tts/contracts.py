from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.character_language import CharacterUtterance
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    utc_instant,
)
from app.domain.speech_performance import SpeechPerformancePlan, validate_plan_segments


class TTSSynthesisStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class TTSFailureCode(str, Enum):
    INVALID_BINDING = "invalid_binding"
    INVALID_REQUEST = "invalid_request"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    REQUEST_TIMEOUT = "request_timeout"
    PROVIDER_SERVER_ERROR = "provider_server_error"
    PROVIDER_REJECTED = "provider_rejected"
    AUDIO_DECODE_OR_STORAGE_FAILED = "audio_decode_or_storage_failed"
    CANCELLED = "cancelled"


class TTSDegradationReason(str, Enum):
    TIMING_UNAVAILABLE = "timing_unavailable"
    UNSUPPORTED_DIMENSION = "unsupported_dimension"
    ARTIFACT_DISCARDED = "artifact_discarded"


class TTSSynthesisPriority(str, Enum):
    FOREGROUND = "foreground"
    SPECULATIVE = "speculative"


class SpeechTimingKind(str, Enum):
    PHONEME = "phoneme"
    MORA = "mora"
    VISEME = "viseme"
    WORD_BOUNDARY = "word_boundary"


class SpeechTimingSourceKind(str, Enum):
    PROVIDER_OBSERVED = "provider_observed"


class SpeechTimingQuality(str, Enum):
    TRUSTWORTHY = "trustworthy"


@dataclass(frozen=True, slots=True)
class TTSVoiceBinding:
    binding_id: str
    character_id: str
    provider_id: str
    provider_voice_ref: str
    binding_revision: int
    locale: str
    enabled: bool
    metadata_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("binding_id", "character_id", "provider_id", "provider_voice_ref", "locale"):
            require_identifier(getattr(self, name), name)
        require_revision(self.binding_revision, "binding_revision")
        if type(self.enabled) is not bool:
            raise ValueError("enabled が不正です")
        refs = tuple(self.metadata_refs)
        if any(not isinstance(item, str) or not item.strip() for item in refs):
            raise ValueError("metadata_refs が不正です")
        object.__setattr__(self, "metadata_refs", refs)


@dataclass(frozen=True, slots=True)
class TTSCapabilityView:
    provider_id: str
    provider_revision: int
    voice_binding_revision: int
    supports_rate: bool
    supports_pitch_center: bool
    supports_pitch_range: bool
    supports_loudness: bool
    supports_breathiness: bool
    supports_phrase_pause: bool
    supports_pronunciation_override: bool
    supports_phoneme_timing: bool
    supports_mora_timing: bool
    supports_viseme_timing: bool
    supports_streaming_audio: bool
    max_text_length: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.provider_id, "provider_id")
        require_revision(self.provider_revision, "provider_revision")
        require_revision(self.voice_binding_revision, "voice_binding_revision")
        if self.max_text_length is not None and (
            type(self.max_text_length) is not int or self.max_text_length < 1
        ):
            raise ValueError("max_text_length が不正です")


@dataclass(frozen=True, slots=True)
class PronunciationOverrideView:
    override_id: str
    surface: str
    reading: str
    locale: str
    source_owner: str
    revision: int

    def __post_init__(self) -> None:
        for name in ("override_id", "surface", "reading", "locale", "source_owner"):
            require_identifier(getattr(self, name), name)
        require_revision(self.revision, "revision")
        if self.surface == self.reading:
            raise ValueError("pronunciation override は読みを変更しなければなりません")


@dataclass(frozen=True, slots=True)
class TTSSynthesisRequest:
    request_id: str
    candidate_id: str
    utterance: CharacterUtterance
    performance_plan: SpeechPerformancePlan
    voice_binding: TTSVoiceBinding
    capability: TTSCapabilityView
    pronunciation_overrides: tuple[PronunciationOverrideView, ...]
    provider_config_revision: int
    pronunciation_config_revision: int
    mapping_id: str
    mapping_revision: int
    retry_policy_id: str
    retry_policy_revision: int
    priority: TTSSynthesisPriority
    created_at: datetime
    trace_id: str
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "candidate_id",
            "mapping_id",
            "retry_policy_id",
            "trace_id",
        ):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.utterance, CharacterUtterance) or not isinstance(
            self.performance_plan, SpeechPerformancePlan
        ):
            raise ValueError("utterance/performance_plan が不正です")
        if not isinstance(self.voice_binding, TTSVoiceBinding) or not isinstance(
            self.capability, TTSCapabilityView
        ):
            raise ValueError("binding/capability が不正です")
        require_revision(self.provider_config_revision, "provider_config_revision")
        require_revision(self.pronunciation_config_revision, "pronunciation_config_revision")
        require_revision(self.mapping_revision, "mapping_revision")
        require_revision(self.retry_policy_revision, "retry_policy_revision")
        require_aware(self.created_at, "created_at")
        if self.deadline_at is not None:
            require_aware(self.deadline_at, "deadline_at")
            if utc_instant(self.deadline_at) <= utc_instant(self.created_at):
                raise ValueError("deadline_atはcreated_atより後でなければなりません")
        if self.performance_plan.utterance_id != self.utterance.utterance_id:
            raise ValueError("performance planのutteranceが一致しません")
        validate_plan_segments(self.utterance, self.performance_plan)
        if self.performance_plan.character_id != self.utterance.candidate.character_id:
            raise ValueError("performance planのCharacterが一致しません")
        if self.voice_binding.character_id != self.utterance.candidate.character_id:
            raise ValueError("voice bindingのCharacterが一致しません")
        if not self.voice_binding.enabled:
            raise ValueError("voice bindingが利用不能です")
        if self.capability.provider_id != self.voice_binding.provider_id or (
            self.capability.voice_binding_revision != self.voice_binding.binding_revision
        ):
            raise ValueError("capability provenanceがbindingと一致しません")
        overrides = tuple(self.pronunciation_overrides)
        if any(not isinstance(item, PronunciationOverrideView) for item in overrides):
            raise ValueError("pronunciation_overrides が不正です")
        if len({item.override_id for item in overrides}) != len(overrides):
            raise ValueError("override_id は一意です")
        if len({item.surface for item in overrides}) != len(overrides):
            raise ValueError("pronunciation override のsurfaceは一意です")
        utterance_text = "".join(segment.text for segment in self.utterance.candidate.segments)
        if (
            self.capability.max_text_length is not None
            and len(utterance_text) > self.capability.max_text_length
        ):
            raise ValueError("utterance text がprovider capabilityの上限を超えます")
        if any(item.surface not in utterance_text for item in overrides):
            raise ValueError("pronunciation override のsurfaceがutteranceに存在しません")
        if not isinstance(self.priority, TTSSynthesisPriority):
            raise ValueError("priority が不正です")
        object.__setattr__(self, "pronunciation_overrides", overrides)


@dataclass(frozen=True, slots=True)
class PreparedAudioArtifact:
    audio_artifact_id: str
    request_id: str
    candidate_id: str
    utterance_id: str
    performance_plan_id: str
    voice_binding_id: str
    voice_binding_revision: int
    provider_revision: int
    provider_config_revision: int
    pronunciation_config_revision: int
    mapping_id: str
    mapping_revision: int
    retry_policy_id: str
    retry_policy_revision: int
    audio_ref: str
    audio_format: str
    content_digest: str
    created_at: datetime
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "audio_artifact_id",
            "request_id",
            "candidate_id",
            "utterance_id",
            "performance_plan_id",
            "voice_binding_id",
            "mapping_id",
            "retry_policy_id",
            "audio_ref",
            "audio_format",
            "content_digest",
        ):
            require_identifier(getattr(self, name), name)
        require_revision(self.voice_binding_revision, "voice_binding_revision")
        require_revision(self.provider_revision, "provider_revision")
        require_revision(self.provider_config_revision, "provider_config_revision")
        require_revision(self.pronunciation_config_revision, "pronunciation_config_revision")
        require_revision(self.mapping_revision, "mapping_revision")
        require_revision(self.retry_policy_revision, "retry_policy_revision")
        require_aware(self.created_at, "created_at")
        if self.duration_ms is not None and (
            type(self.duration_ms) is not int or self.duration_ms < 1
        ):
            raise ValueError("duration_ms が不正です")


@dataclass(frozen=True, slots=True)
class SpeechTimingUnit:
    unit_id: str
    segment_id: str
    kind: SpeechTimingKind
    symbol: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        for name in ("unit_id", "segment_id", "symbol"):
            require_identifier(getattr(self, name), name)
        if (
            not isinstance(self.kind, SpeechTimingKind)
            or type(self.start_ms) is not int
            or type(self.end_ms) is not int
            or self.start_ms < 0
            or self.end_ms <= self.start_ms
        ):
            raise ValueError("timing unit が不正です")


@dataclass(frozen=True, slots=True)
class SpeechTimingTrack:
    timing_track_id: str
    audio_artifact_id: str
    units: tuple[SpeechTimingUnit, ...]
    created_at: datetime
    audio_duration_ms: int | None = None
    source_kind: SpeechTimingSourceKind = SpeechTimingSourceKind.PROVIDER_OBSERVED
    quality: SpeechTimingQuality = SpeechTimingQuality.TRUSTWORTHY

    def __post_init__(self) -> None:
        require_identifier(self.timing_track_id, "timing_track_id")
        require_identifier(self.audio_artifact_id, "audio_artifact_id")
        if not isinstance(self.source_kind, SpeechTimingSourceKind) or not isinstance(
            self.quality, SpeechTimingQuality
        ):
            raise ValueError("timing source/quality が不正です")
        units = tuple(self.units)
        if any(not isinstance(unit, SpeechTimingUnit) for unit in units):
            raise ValueError("timing units が不正です")
        if any(left.end_ms > right.start_ms for left, right in zip(units, units[1:], strict=False)):
            raise ValueError("timingは単調でなければなりません")
        if self.audio_duration_ms is not None and (
            type(self.audio_duration_ms) is not int
            or self.audio_duration_ms < 1
            or any(unit.end_ms > self.audio_duration_ms for unit in units)
        ):
            raise ValueError("timingがaudio durationの範囲外です")
        object.__setattr__(self, "units", units)
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class TTSSynthesisResult:
    request_id: str
    status: TTSSynthesisStatus
    attempts: int
    completed_at: datetime
    artifact: PreparedAudioArtifact | None = None
    timing_track: SpeechTimingTrack | None = None
    degradation_reasons: tuple[TTSDegradationReason, ...] = ()
    applied_dimensions: tuple[str, ...] = ()
    degraded_dimensions: tuple[str, ...] = ()
    failure_code: TTSFailureCode | None = None

    def __post_init__(self) -> None:
        require_identifier(self.request_id, "request_id")
        if (
            not isinstance(self.status, TTSSynthesisStatus)
            or type(self.attempts) is not int
            or self.attempts < 0
        ):
            raise ValueError("synthesis result が不正です")
        require_aware(self.completed_at, "completed_at")
        reasons = tuple(self.degradation_reasons)
        if any(not isinstance(item, TTSDegradationReason) for item in reasons):
            raise ValueError("degradation_reasons が不正です")
        object.__setattr__(self, "degradation_reasons", reasons)
        for name in ("applied_dimensions", "degraded_dimensions"):
            dimensions = tuple(getattr(self, name))
            if any(not isinstance(item, str) or not item.strip() for item in dimensions) or len(
                dimensions
            ) != len(set(dimensions)):
                raise ValueError(f"{name} が不正です")
            object.__setattr__(self, name, dimensions)
        if self.status is TTSSynthesisStatus.SUCCEEDED:
            if (
                not isinstance(self.artifact, PreparedAudioArtifact)
                or self.failure_code is not None
            ):
                raise ValueError("successful resultが不正です")
            if (
                self.timing_track is not None
                and self.timing_track.audio_artifact_id != self.artifact.audio_artifact_id
            ):
                raise ValueError("timing artifactが一致しません")
        elif (
            self.artifact is not None
            or self.timing_track is not None
            or not isinstance(self.failure_code, TTSFailureCode)
        ):
            raise ValueError("failed resultが不正です")
