from __future__ import annotations

import asyncio

import pytest

from cloud_validation.character_reference_asr_lab import (
    AnalyzeRequest,
    CharacterReferenceLabService,
    LabSettings,
)
from tools.character_reference_analysis.asr_coordinator import (
    AsrProcessingOutcome,
    AsrProcessingResult,
)
from tools.character_reference_analysis.models import (
    ReferenceSource,
    ReferenceSourceKind,
    Transcript,
    TranscriptSegment,
    TranscriptionMetadata,
)
from tools.character_reference_analysis.progress import ProgressCallback


def make_source() -> ReferenceSource:
    return ReferenceSource(
        reference_id="drive:progress-video",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="drive-file:progress-video",
        display_name="progress.mov",
        content_hash="md5:progress",
    )


def make_settings() -> LabSettings:
    return LabSettings(
        inbox_folder_id="inbox",
        results_folder_id="results",
        asr_model="test",
        username="user",
        password="pass",
    )


class FakeStore:
    pass


class ProgressPipeline:
    def __init__(self, source: ReferenceSource) -> None:
        self.source = source

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return (self.source,)

    async def process_source(
        self,
        source: ReferenceSource,
        *,
        language: str | None = "ja",
        retry: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> AsrProcessingResult:
        assert source == self.source
        assert language == "ja"
        assert retry is False
        assert progress_callback is not None
        for stage, percent in (
            ("downloading_video", 5),
            ("video_downloaded", 30),
            ("extracting_audio", 35),
            ("audio_extracted", 45),
            ("transcribing", 60),
            ("saving_transcript", 85),
            ("completed", 100),
        ):
            await progress_callback(stage, percent)
            await asyncio.sleep(0)

        transcript = Transcript(
            reference_id=source.reference_id,
            text="進捗確認用の文字起こしです。",
            segments=(
                TranscriptSegment(
                    text="進捗確認用の文字起こしです。",
                    start_seconds=0.0,
                    end_seconds=1.0,
                    language="ja",
                    speaker="A",
                ),
            ),
            metadata=TranscriptionMetadata(
                provider="fake",
                model="fake",
                requested_language="ja",
                detected_language="ja",
                response_format="diarized_json",
            ),
        )
        return AsrProcessingResult(
            outcome=AsrProcessingOutcome.COMPLETED,
            revision_key="drive:progress-video@md5:progress",
            transcript=transcript,
        )


@pytest.mark.asyncio
async def test_background_analysis_job_reaches_completed_progress() -> None:
    source = make_source()
    service = CharacterReferenceLabService(
        make_settings(),
        pipeline=ProgressPipeline(source),
        store=FakeStore(),  # type: ignore[arg-type]
    )

    started = await service.start_analysis(AnalyzeRequest(reference_id=source.reference_id))

    assert started["state"] == "queued"
    job_id = str(started["job_id"])

    final: dict[str, object] | None = None
    for _ in range(50):
        snapshot = await service.analysis_progress(job_id)
        if snapshot["state"] not in {"queued", "running"}:
            final = snapshot
            break
        await asyncio.sleep(0)

    assert final is not None
    assert final["state"] == "completed"
    assert final["stage"] == "completed"
    assert final["percent"] == 100
    assert final["outcome"] == "completed"
    assert final["segment_count"] == 1
    assert final["transcript_preview"] == "進捗確認用の文字起こしです。"


@pytest.mark.asyncio
async def test_start_analysis_reuses_active_job_for_same_reference() -> None:
    source = make_source()
    gate = asyncio.Event()

    class WaitingPipeline(ProgressPipeline):
        async def process_source(
            self,
            source: ReferenceSource,
            *,
            language: str | None = "ja",
            retry: bool = False,
            progress_callback: ProgressCallback | None = None,
        ) -> AsrProcessingResult:
            assert progress_callback is not None
            await progress_callback("transcribing", 60)
            await gate.wait()
            return AsrProcessingResult(
                outcome=AsrProcessingOutcome.SKIPPED_DUPLICATE,
                revision_key="already-done",
            )

    service = CharacterReferenceLabService(
        make_settings(),
        pipeline=WaitingPipeline(source),
        store=FakeStore(),  # type: ignore[arg-type]
    )

    first = await service.start_analysis(AnalyzeRequest(reference_id=source.reference_id))
    await asyncio.sleep(0)
    second = await service.start_analysis(AnalyzeRequest(reference_id=source.reference_id))

    assert second["job_id"] == first["job_id"]
    gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
