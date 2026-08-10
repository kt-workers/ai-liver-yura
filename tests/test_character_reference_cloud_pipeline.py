from __future__ import annotations

from pathlib import Path

import pytest

from tools.character_reference_analysis.asr_coordinator import (
    AsrProcessingOutcome,
    AsrProcessingResult,
)
from tools.character_reference_analysis.cloud_pipeline import ReferenceCloudAsrPipeline
from tools.character_reference_analysis.google_drive import GoogleDriveReferenceInbox
from tools.character_reference_analysis.media_normalizer import FfmpegAudioNormalizer
from tools.character_reference_analysis.models import (
    ReferenceSource,
    ReferenceSourceKind,
)


class FakeRequest:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def execute(self) -> dict[str, object]:
        return self._payload


class FakeFiles:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.last_list_kwargs: dict[str, object] | None = None

    def list(self, **kwargs: object) -> FakeRequest:
        self.last_list_kwargs = kwargs
        return FakeRequest(self._payload)


class FakeDriveService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.files_resource = FakeFiles(payload)

    def files(self) -> FakeFiles:
        return self.files_resource


@pytest.mark.asyncio
async def test_drive_inbox_lists_only_video_sources() -> None:
    service = FakeDriveService(
        {
            "files": [
                {
                    "id": "video-1",
                    "name": "reference.mov",
                    "mimeType": "video/quicktime",
                    "md5Checksum": "abc123",
                    "version": "7",
                    "size": "52790619",
                    "thumbnailLink": "https://example.invalid/thumbnail",
                    "videoMediaMetadata": {
                        "durationMillis": "28440",
                        "width": 1320,
                        "height": 2868,
                    },
                },
                {
                    "id": "text-1",
                    "name": "notes.txt",
                    "mimeType": "text/plain",
                },
            ]
        }
    )
    inbox = GoogleDriveReferenceInbox(service=service, folder_id="folder-1")

    sources = await inbox.list_sources()

    assert len(sources) == 1
    assert sources[0].reference_id == "drive:video-1"
    assert sources[0].source_kind == ReferenceSourceKind.GOOGLE_DRIVE_VIDEO
    assert sources[0].source_locator == "drive-file:video-1"
    assert sources[0].content_hash == "md5:abc123"
    assert sources[0].size_bytes == 52790619
    assert sources[0].duration_seconds == pytest.approx(28.44)
    assert sources[0].thumbnail_available is True
    assert service.files_resource.last_list_kwargs is not None
    fields = str(service.files_resource.last_list_kwargs["fields"])
    assert "thumbnailLink" in fields
    assert "videoMediaMetadata" in fields


def test_ffmpeg_normalizer_extracts_audio_only_command(tmp_path: Path) -> None:
    media = tmp_path / "reference.mov"
    output = tmp_path / "reference-audio.mp3"
    normalizer = FfmpegAudioNormalizer(sample_rate=16000, bitrate="64k")

    command = normalizer._build_command("ffmpeg", media, output)

    assert command[0] == "ffmpeg"
    assert "-vn" in command
    assert ["-ac", "1"] == command[command.index("-ac") : command.index("-ac") + 2]
    assert ["-ar", "16000"] == command[
        command.index("-ar") : command.index("-ar") + 2
    ]
    assert command[-1] == str(output)


class FakeInbox:
    def __init__(self, source: ReferenceSource) -> None:
        self.source = source
        self.materialized_path: Path | None = None

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return (self.source,)

    async def materialize(self, source: ReferenceSource, work_directory: Path) -> Path:
        assert source == self.source
        path = work_directory / "source.mov"
        path.write_bytes(b"video")
        self.materialized_path = path
        return path


class FakeNormalizer:
    def __init__(self) -> None:
        self.audio_path: Path | None = None

    async def extract_audio(self, media_path: Path, output_directory: Path) -> Path:
        assert media_path.is_file()
        path = output_directory / "reference-audio.mp3"
        path.write_bytes(b"audio")
        self.audio_path = path
        return path


class FakeCoordinator:
    async def process(
        self,
        source: ReferenceSource,
        media_path: Path,
        *,
        language: str | None = "ja",
        retry: bool = False,
    ) -> AsrProcessingResult:
        assert media_path.is_file()
        assert media_path.suffix == ".mp3"
        assert language == "ja"
        assert retry is False
        return AsrProcessingResult(
            outcome=AsrProcessingOutcome.COMPLETED,
            revision_key=f"{source.reference_id}@hash",
        )


@pytest.mark.asyncio
async def test_cloud_pipeline_uses_ephemeral_media_only() -> None:
    source = ReferenceSource(
        reference_id="drive:video-1",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="drive-file:video-1",
        display_name="source.mov",
        content_hash="hash",
    )
    inbox = FakeInbox(source)
    normalizer = FakeNormalizer()
    pipeline = ReferenceCloudAsrPipeline(
        inbox=inbox,
        normalizer=normalizer,
        coordinator=FakeCoordinator(),  # type: ignore[arg-type]
    )

    result = await pipeline.process_source(source)

    assert result.outcome == AsrProcessingOutcome.COMPLETED
    assert inbox.materialized_path is not None
    assert normalizer.audio_path is not None
    assert inbox.materialized_path.exists() is False
    assert normalizer.audio_path.exists() is False
