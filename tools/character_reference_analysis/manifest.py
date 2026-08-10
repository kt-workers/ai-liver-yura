from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .models import ReferenceSource


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnalysisStepStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ReferenceAnalysisManifest:
    reference_id: str
    revision_key: str
    asr_status: AnalysisStepStatus = AnalysisStepStatus.PENDING
    audio_analysis_status: AnalysisStepStatus = AnalysisStepStatus.PENDING
    visual_analysis_status: AnalysisStepStatus = AnalysisStepStatus.PENDING
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    last_error: str | None = None

    @classmethod
    def for_source(cls, source: ReferenceSource) -> "ReferenceAnalysisManifest":
        return cls(
            reference_id=source.reference_id,
            revision_key=build_revision_key(source),
        )

    def with_asr_status(
        self,
        status: AnalysisStepStatus,
        *,
        error: str | None = None,
    ) -> "ReferenceAnalysisManifest":
        return replace(
            self,
            asr_status=status,
            updated_at=_utc_now_iso(),
            last_error=error,
        )

    @property
    def is_fully_completed(self) -> bool:
        return all(
            status == AnalysisStepStatus.COMPLETED
            for status in (
                self.asr_status,
                self.audio_analysis_status,
                self.visual_analysis_status,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["asr_status"] = self.asr_status.value
        value["audio_analysis_status"] = self.audio_analysis_status.value
        value["visual_analysis_status"] = self.visual_analysis_status.value
        return value


def build_revision_key(source: ReferenceSource) -> str:
    """Stable analysis key used to prevent duplicate provider/API work.

    Binary Drive files expose a content checksum; when available it makes an updated
    file a new analysis revision. Without one, the stable reference ID is used and
    explicit retry is required to re-run the source.
    """

    if source.content_hash:
        return f"{source.reference_id}@{source.content_hash}"
    return source.reference_id
