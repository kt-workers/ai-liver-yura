from __future__ import annotations

from pathlib import Path

import pytest

from cloud_validation.character_reference_asr_lab import (
    CharacterReferenceLabService,
    LabSettings,
)
from tools.character_reference_analysis.cloud_pipeline import ReferenceCloudAsrPipeline
from tools.character_reference_analysis.models import ReferenceSource, ReferenceSourceKind
from tools.character_reference_analysis.thumbnailer import FfmpegReferenceThumbnailer


def make_source() -> ReferenceSource:
    return ReferenceSource(
        reference_id="drive:video-1",
        source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
        source_locator="drive-file:video-1",
        display_name="reference.mov",
        content_hash="md5:preview-source",
        thumbnail_available=False,
    )


class FakeInbox:
    def __init__(self, source: ReferenceSource) -> None:
        self.source = source
        self.materialized_path: Path | None = None

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return (self.source,)

    async def materialize(self, source: ReferenceSource, work_directory: Path) -> Path:
        assert source == self.source
        path = work_directory / "reference.mov"
        path.write_bytes(b"video")
        self.materialized_path = path
        return path


class FakeThumbnailer:
    def __init__(self) -> None:
        self.preview_path: Path | None = None

    async def extract_thumbnail(
        self,
        media_path: Path,
        output_directory: Path,
    ) -> Path:
        assert media_path.is_file()
        path = output_directory / "preview.jpg"
        path.write_bytes(b"jpeg-preview")
        self.preview_path = path
        return path


@pytest.mark.asyncio
async def test_generated_preview_uses_ephemeral_source_media() -> None:
    source = make_source()
    inbox = FakeInbox(source)
    thumbnailer = FakeThumbnailer()
    pipeline = ReferenceCloudAsrPipeline(
        inbox=inbox,
        normalizer=object(),  # type: ignore[arg-type]
        coordinator=object(),  # type: ignore[arg-type]
        thumbnailer=thumbnailer,  # type: ignore[arg-type]
    )

    payload = await pipeline.generate_thumbnail(source)

    assert payload == (b"jpeg-preview", "image/jpeg")
    assert inbox.materialized_path is not None
    assert thumbnailer.preview_path is not None
    assert inbox.materialized_path.exists() is False
    assert thumbnailer.preview_path.exists() is False


class FakePipeline:
    def __init__(self, source: ReferenceSource) -> None:
        self.source = source
        self.generate_calls = 0

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return (self.source,)

    async def generate_thumbnail(
        self,
        source: ReferenceSource,
    ) -> tuple[bytes, str]:
        assert source == self.source
        self.generate_calls += 1
        return b"generated-preview", "image/jpeg"


class FakeResultStore:
    pass


class FakePreviewStore:
    def __init__(self) -> None:
        self.payload: tuple[bytes, str] | None = None
        self.saved_revision_key: str | None = None

    async def load(self, revision_key: str) -> tuple[bytes, str] | None:
        return self.payload

    async def save(
        self,
        revision_key: str,
        content: bytes,
        media_type: str,
    ) -> None:
        self.saved_revision_key = revision_key
        self.payload = content, media_type


@pytest.mark.asyncio
async def test_lab_generates_and_reuses_cached_preview_when_drive_has_none() -> None:
    source = make_source()
    pipeline = FakePipeline(source)
    preview_store = FakePreviewStore()
    service = CharacterReferenceLabService(
        LabSettings(
            inbox_folder_id="inbox",
            results_folder_id="results",
            asr_model="test",
            username="user",
            password="pass",
        ),
        pipeline=pipeline,  # type: ignore[arg-type]
        store=FakeResultStore(),  # type: ignore[arg-type]
        preview_store=preview_store,
    )

    first = await service.thumbnail(source.reference_id)
    second = await service.thumbnail(source.reference_id)

    assert first == (b"generated-preview", "image/jpeg")
    assert second == first
    assert pipeline.generate_calls == 1
    assert preview_store.saved_revision_key is not None


def test_thumbnailer_command_extracts_one_scaled_jpeg() -> None:
    thumbnailer = FfmpegReferenceThumbnailer(width=320, seek_seconds=0.5)
    command = thumbnailer._build_command(
        "ffmpeg",
        Path("reference.mov"),
        Path("preview.jpg"),
        seek_seconds=0.5,
    )

    assert command[:4] == ["ffmpeg", "-y", "-ss", "0.500"]
    assert ["-frames:v", "1"] == command[
        command.index("-frames:v") : command.index("-frames:v") + 2
    ]
    assert ["-vf", "scale=320:-2"] == command[
        command.index("-vf") : command.index("-vf") + 2
    ]
