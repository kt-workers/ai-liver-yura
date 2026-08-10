from __future__ import annotations

from pathlib import Path

import pytest

from tools.character_reference_analysis.asr_coordinator import (
    AsrProcessingOutcome,
    AsrProcessingResult,
)
from tools.character_reference_analysis.cloud_pipeline import ReferenceCloudAsrPipeline
from tools.character_reference_analysis.models import ReferenceSource, ReferenceSourceKind
from tools.character_reference_analysis.progress import ProgressCallback


class ProgressiveInbox:
    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return ()

    async def materialize(self, source: ReferenceSource, work_directory: Path) -> Path:
        path = work_directory / source.display_name
        path.write_bytes(b"video")
        return path

    async def materialize_with_progress(
        self,
        source: ReferenceSource,
        work_directory: Path,
        *,
        progress_callback: ProgressCallback,
    ) -> Path:
        path = work_directory / source.display_name
        for percent in (5, 15, 30):
            await progress_callback("downloading_video", percent)
        path.write_bytes(b"video")
        return path


class FakeNormalizer:
    async def extract_audio(self, media_path: Path, output_directory: Path) -> Path:
        path = output_directory / "audio.mp3"
        path.write_bytes(b"audio")
        return path


class FakeCoordinator:
    async def process(
        self,
        source: ReferenceSource,
        media_path: Path,
        *,
        language: str | None = "ja",
        retry: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> AsrProcessingResult:
        return AsrProcessingResult(
            outcome=AsrProcessingOutcome.COMPLETED,
            revision_key=source.reference_id,
        )


@pytest.mark.asyncio
async def test_pipeline_reports_progress_inside_drive_download_range() -> None:
    source = ReferenceSource(
        reference_id="drive:video-progress",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="drive-file:video-progress",
        display_name="reference.mov",
    )
    observed: list[tuple[str, int]] = []

    async def progress(stage: str, percent: int) -> None:
        observed.append((stage, percent))

    pipeline = ReferenceCloudAsrPipeline(
        inbox=ProgressiveInbox(),
        normalizer=FakeNormalizer(),  # type: ignore[arg-type]
        coordinator=FakeCoordinator(),  # type: ignore[arg-type]
    )

    result = await pipeline.process_source(source, progress_callback=progress)

    assert result.outcome == AsrProcessingOutcome.COMPLETED
    download_values = [
        percent for stage, percent in observed if stage == "downloading_video"
    ]
    assert download_values == [5, 5, 15, 30]
    assert ("video_downloaded", 30) in observed
