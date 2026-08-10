from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .manifest import AnalysisStepStatus, ReferenceAnalysisManifest, build_revision_key
from .models import ReferenceSource, Transcript
from .ports import TranscriptionBackend
from .store import ReferenceResultStore


class AsrProcessingOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"


@dataclass(frozen=True, slots=True)
class AsrProcessingResult:
    outcome: AsrProcessingOutcome
    revision_key: str
    transcript: Transcript | None = None
    error: str | None = None


class ReferenceAsrCoordinator:
    """Coordinates reference-only ASR without duplicating paid provider work."""

    def __init__(
        self,
        *,
        backend: TranscriptionBackend,
        store: ReferenceResultStore,
    ) -> None:
        self._backend = backend
        self._store = store

    async def process(
        self,
        source: ReferenceSource,
        media_path: Path,
        *,
        language: str | None = "ja",
        retry: bool = False,
    ) -> AsrProcessingResult:
        revision_key = build_revision_key(source)
        if not retry and await self._store.has_revision(revision_key):
            return AsrProcessingResult(
                outcome=AsrProcessingOutcome.SKIPPED_DUPLICATE,
                revision_key=revision_key,
            )

        existing = await self._store.load_manifest(revision_key)
        manifest = existing or ReferenceAnalysisManifest.for_source(source)
        manifest = manifest.with_asr_status(AnalysisStepStatus.PROCESSING)
        await self._store.save_manifest(manifest)

        try:
            transcript = await self._backend.transcribe(
                media_path,
                reference_id=source.reference_id,
                language=language,
            )
            await self._store.save_transcript(transcript, revision_key=revision_key)
        except Exception as error:  # boundary intentionally records provider/storage failures
            failed = manifest.with_asr_status(
                AnalysisStepStatus.FAILED,
                error=f"{type(error).__name__}: {error}",
            )
            await self._store.save_manifest(failed)
            return AsrProcessingResult(
                outcome=AsrProcessingOutcome.FAILED,
                revision_key=revision_key,
                error=failed.last_error,
            )

        completed = manifest.with_asr_status(AnalysisStepStatus.COMPLETED)
        await self._store.save_manifest(completed)
        return AsrProcessingResult(
            outcome=AsrProcessingOutcome.COMPLETED,
            revision_key=revision_key,
            transcript=transcript,
        )
