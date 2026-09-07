"""音声成果と観測時刻の公開契約。具体的な音声合成処理を読み込まない。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .common import require_aware, require_identifier, require_revision


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
