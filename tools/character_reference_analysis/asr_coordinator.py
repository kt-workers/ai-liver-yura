from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .manifest import AnalysisStepStatus, ReferenceAnalysisManifest, build_revision_key
from .models import ReferenceSource, Transcript
from .ports import TranscriptionBackend
from .progress import ProgressCallback, report_progress
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
        progress_callback: ProgressCallback | None = None,
    ) -> AsrProcessingResult:
        revision_key = build_revision_key(source)
        await report_progress(progress_callback, "checking_duplicate", 50)
        existing = await self._store.load_manifest(revision_key)

        if existing is not None and not retry:
            if existing.asr_status == AnalysisStepStatus.COMPLETED:
                await report_progress(progress_callback, "skipped_duplicate", 100)
                return AsrProcessingResult(
                    outcome=AsrProcessingOutcome.SKIPPED_DUPLICATE,
                    revision_key=revision_key,
                )
            if existing.asr_status == AnalysisStepStatus.PROCESSING:
                if await self._has_transcript(revision_key):
                    recovered = existing.with_asr_status(AnalysisStepStatus.COMPLETED)
                    await self._store.save_manifest(recovered)
                    await report_progress(progress_callback, "recovered_completed", 100)
                    return AsrProcessingResult(
                        outcome=AsrProcessingOutcome.SKIPPED_DUPLICATE,
                        revision_key=revision_key,
                    )
                existing = existing.with_asr_status(
                    AnalysisStepStatus.INTERRUPTED,
                    error="previous ASR process was interrupted before transcript persistence",
                )
                await self._store.save_manifest(existing)
            elif existing.asr_status == AnalysisStepStatus.FAILED:
                await report_progress(progress_callback, "retry_required", 100)
                return AsrProcessingResult(
                    outcome=AsrProcessingOutcome.FAILED,
                    revision_key=revision_key,
                    error=existing.last_error or "previous ASR attempt failed; retry is required",
                )

        await report_progress(progress_callback, "preparing_asr", 55)
        manifest = existing or ReferenceAnalysisManifest.for_source(source)
        manifest = manifest.with_asr_status(AnalysisStepStatus.PROCESSING)
        await self._store.save_manifest(manifest)

        try:
            await report_progress(progress_callback, "transcribing", 60)
            transcript = await self._backend.transcribe(
                media_path,
                reference_id=source.reference_id,
                language=language,
            )
            await report_progress(progress_callback, "saving_transcript", 85)
            await self._store.save_transcript(transcript, revision_key=revision_key)
        except asyncio.CancelledError:
            interrupted = manifest.with_asr_status(
                AnalysisStepStatus.INTERRUPTED,
                error="ASR analysis was canceled or interrupted",
            )
            await self._store.save_manifest(interrupted)
            await report_progress(progress_callback, "canceled", 100)
            raise
        except Exception as error:  # boundary intentionally records provider/storage failures
            failed = manifest.with_asr_status(
                AnalysisStepStatus.FAILED,
                error=f"{type(error).__name__}: {error}",
            )
            await self._store.save_manifest(failed)
            await report_progress(progress_callback, "failed", 100)
            return AsrProcessingResult(
                outcome=AsrProcessingOutcome.FAILED,
                revision_key=revision_key,
                error=failed.last_error,
            )

        await report_progress(progress_callback, "finalizing", 95)
        completed = manifest.with_asr_status(AnalysisStepStatus.COMPLETED)
        await self._store.save_manifest(completed)
        await report_progress(progress_callback, "completed", 100)
        return AsrProcessingResult(
            outcome=AsrProcessingOutcome.COMPLETED,
            revision_key=revision_key,
            transcript=transcript,
        )

    async def _has_transcript(self, revision_key: str) -> bool:
        checker = getattr(self._store, "has_transcript", None)
        if checker is None:
            return False
        return bool(await checker(revision_key))
