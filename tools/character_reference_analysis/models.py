from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ReferenceSourceKind(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    YOUTUBE = "youtube"
    UPLOADED_FILE = "uploaded_file"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ReferenceUsagePolicy:
    """Hard boundary: source media is observation material, never Yura assets."""

    purpose: str = "reference_only"
    allow_original_media_reuse: bool = False
    allow_voice_reuse: bool = False
    allow_utterance_reuse: bool = False
    allow_motion_reuse: bool = False
    allow_character_setting_copy: bool = False

    def __post_init__(self) -> None:
        if self.purpose != "reference_only":
            raise ValueError("reference source purpose must remain reference_only")
        if any(
            (
                self.allow_original_media_reuse,
                self.allow_voice_reuse,
                self.allow_utterance_reuse,
                self.allow_motion_reuse,
                self.allow_character_setting_copy,
            )
        ):
            raise ValueError("reference source reuse must remain disabled")


@dataclass(frozen=True, slots=True)
class ReferenceSource:
    reference_id: str
    source_kind: ReferenceSourceKind
    source_uri: str
    display_name: str
    content_hash: str | None = None
    usage_policy: ReferenceUsagePolicy = field(default_factory=ReferenceUsagePolicy)

    def __post_init__(self) -> None:
        if not self.reference_id.strip():
            raise ValueError("reference_id must not be empty")
        if not self.source_uri.strip():
            raise ValueError("source_uri must not be empty")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_kind"] = self.source_kind.value
        return value


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    speaker: str | None = None
    confidence: float | None = None

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
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class TranscriptionMetadata:
    provider: str
    model: str
    requested_language: str | None
    detected_language: str | None
    response_format: str
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
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
