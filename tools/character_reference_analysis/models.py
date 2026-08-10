from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReferenceSourceKind(str, Enum):
    GOOGLE_DRIVE_VIDEO = "google_drive_video"
    YOUTUBE_VIDEO = "youtube_video"
    UPLOADED_VIDEO = "uploaded_video"
    OTHER = "other"


class ReferenceAnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ObservationAdoptionStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    CANDIDATE = "candidate"
    HOLD = "hold"
    REJECTED = "rejected"
    ADOPTED = "adopted"


class ObservationAbstractionLevel(str, Enum):
    BEHAVIORAL_PATTERN = "behavioral_pattern"
    INTERACTION_PATTERN = "interaction_pattern"
    LANGUAGE_PATTERN = "language_pattern"
    AUDIO_EXPRESSION_PATTERN = "audio_expression_pattern"
    VISUAL_EXPRESSION_PATTERN = "visual_expression_pattern"


@dataclass(frozen=True, slots=True)
class ReferenceUsagePolicy:
    """Hard boundary: source media is observation material, never Yura assets."""

    source_usage: str = "reference_only"
    verbatim_reuse_allowed: bool = False
    voice_clone_allowed: bool = False
    motion_copy_allowed: bool = False
    asset_reuse_allowed: bool = False
    character_setting_auto_adoption: bool = False

    def __post_init__(self) -> None:
        if self.source_usage != "reference_only":
            raise ValueError("reference source usage must remain reference_only")
        if any(
            (
                self.verbatim_reuse_allowed,
                self.voice_clone_allowed,
                self.motion_copy_allowed,
                self.asset_reuse_allowed,
                self.character_setting_auto_adoption,
            )
        ):
            raise ValueError("reference source reuse must remain disabled")


@dataclass(frozen=True, slots=True)
class ReferenceSource:
    reference_id: str
    source_kind: ReferenceSourceKind
    source_locator: str
    display_name: str
    content_hash: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    analysis_status: ReferenceAnalysisStatus = ReferenceAnalysisStatus.PENDING
    usage_policy: ReferenceUsagePolicy = field(default_factory=ReferenceUsagePolicy)

    def __post_init__(self) -> None:
        if not self.reference_id.strip():
            raise ValueError("reference_id must not be empty")
        if not self.source_locator.strip():
            raise ValueError("source_locator must not be empty")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_kind"] = self.source_kind.value
        value["analysis_status"] = self.analysis_status.value
        return value


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    language: str | None = None
    speaker: str | None = None
    asr_confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("segment text must not be empty")
        if self.start_seconds is not None and self.start_seconds < 0:
            raise ValueError("start_seconds must be >= 0")
        if self.end_seconds is not None and self.end_seconds < 0:
            raise ValueError("end_seconds must be >= 0")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("end_seconds must be >= start_seconds")
        if self.asr_confidence is not None and not 0 <= self.asr_confidence <= 1:
            raise ValueError("asr_confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class TranscriptionMetadata:
    provider: str
    model: str
    requested_language: str | None
    detected_language: str | None
    response_format: str
    generated_at: str = field(default_factory=_utc_now_iso)
    source_duration_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be empty")
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if not self.response_format.strip():
            raise ValueError("response_format must not be empty")
        if self.source_duration_seconds is not None and self.source_duration_seconds < 0:
            raise ValueError("source_duration_seconds must be >= 0")


@dataclass(frozen=True, slots=True)
class Transcript:
    reference_id: str
    text: str
    segments: tuple[TranscriptSegment, ...]
    metadata: TranscriptionMetadata

    def __post_init__(self) -> None:
        if not self.reference_id.strip():
            raise ValueError("reference_id must not be empty")
        if not self.text.strip():
            raise ValueError("transcript text must not be empty")

    @property
    def has_timestamps(self) -> bool:
        return bool(self.segments) and all(
            segment.start_seconds is not None and segment.end_seconds is not None
            for segment in self.segments
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AudioExpressionObservation:
    reference_id: str
    start_seconds: float
    end_seconds: float
    speech_rate: str
    pause_pattern: str
    pitch_movement: str
    energy_movement: str
    delivery_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds < self.start_seconds:
            raise ValueError("audio observation time range is invalid")
        for value in (
            self.speech_rate,
            self.pause_pattern,
            self.pitch_movement,
            self.energy_movement,
        ):
            if not value.strip():
                raise ValueError("audio observation fields must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReferenceObservation:
    """Abstract observation only; deliberately has no raw media/transcript field."""

    observation_id: str
    reference_id: str
    category: str
    observation: str
    evidence_refs: tuple[str, ...]
    abstraction_level: ObservationAbstractionLevel
    adoption_status: ObservationAdoptionStatus = ObservationAdoptionStatus.UNREVIEWED

    def __post_init__(self) -> None:
        for name, value in (
            ("observation_id", self.observation_id),
            ("reference_id", self.reference_id),
            ("category", self.category),
            ("observation", self.observation),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not self.evidence_refs:
            raise ValueError("evidence_refs must not be empty")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["abstraction_level"] = self.abstraction_level.value
        value["adoption_status"] = self.adoption_status.value
        return value


@dataclass(frozen=True, slots=True)
class YuraDesignCandidate:
    candidate_id: str
    derived_from_observations: tuple[str, ...]
    yura_specific_design: str
    status: ObservationAdoptionStatus = ObservationAdoptionStatus.CANDIDATE

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if not self.derived_from_observations:
            raise ValueError("derived_from_observations must not be empty")
        if not self.yura_specific_design.strip():
            raise ValueError("yura_specific_design must not be empty")
        if self.status == ObservationAdoptionStatus.UNREVIEWED:
            raise ValueError("YuraDesignCandidate must be an explicit review-stage state")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value
