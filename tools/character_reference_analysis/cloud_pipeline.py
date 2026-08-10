from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol

from .asr_coordinator import AsrProcessingResult, ReferenceAsrCoordinator
from .media_normalizer import ReferenceMediaNormalizer
from .models import ReferenceSource
from .progress import ProgressCallback, report_progress
from .thumbnailer import FfmpegReferenceThumbnailer


class ReferenceInbox(Protocol):
    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        ...

    async def materialize(self, source: ReferenceSource, work_directory: Path) -> Path:
        ...


class ReferenceCloudAsrPipeline:
    """Materialize → extract temporary audio → ASR → discard temporary media."""

    def __init__(
        self,
        *,
        inbox: ReferenceInbox,
        normalizer: ReferenceMediaNormalizer,
        coordinator: ReferenceAsrCoordinator,
        thumbnailer: FfmpegReferenceThumbnailer | None = None,
    ) -> None:
        self._inbox = inbox
        self._normalizer = normalizer
        self._coordinator = coordinator
        self._thumbnailer = thumbnailer

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return await self._inbox.list_sources()

    async def fetch_thumbnail(
        self,
        source: ReferenceSource,
    ) -> tuple[bytes, str] | None:
        fetcher = getattr(self._inbox, "fetch_thumbnail", None)
        if fetcher is None:
            return None
        return await fetcher(source)

    async def generate_thumbnail(
        self,
        source: ReferenceSource,
    ) -> tuple[bytes, str] | None:
        if self._thumbnailer is None:
            return None
        with tempfile.TemporaryDirectory(prefix="yura-reference-preview-") as work_dir:
            work_path = Path(work_dir)
            media_path = await self._inbox.materialize(source, work_path)
            preview_path = await self._thumbnailer.extract_thumbnail(media_path, work_path)
            return preview_path.read_bytes(), "image/jpeg"

    async def process_source(
        self,
        source: ReferenceSource,
        *,
        language: str | None = "ja",
        retry: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> AsrProcessingResult:
        with tempfile.TemporaryDirectory(prefix="yura-reference-") as work_dir:
            work_path = Path(work_dir)
            await report_progress(progress_callback, "downloading_video", 5)
            progressive_materializer = getattr(
                self._inbox,
                "materialize_with_progress",
                None,
            )
            if progress_callback is not None and progressive_materializer is not None:
                media_path = await progressive_materializer(
                    source,
                    work_path,
                    progress_callback=progress_callback,
                )
            else:
                media_path = await self._inbox.materialize(source, work_path)
            await report_progress(progress_callback, "video_downloaded", 30)
            await report_progress(progress_callback, "extracting_audio", 35)
            audio_path = await self._normalizer.extract_audio(media_path, work_path)
            await report_progress(progress_callback, "audio_extracted", 45)
            if progress_callback is None:
                return await self._coordinator.process(
                    source,
                    audio_path,
                    language=language,
                    retry=retry,
                )
            return await self._coordinator.process(
                source,
                audio_path,
                language=language,
                retry=retry,
                progress_callback=progress_callback,
            )
