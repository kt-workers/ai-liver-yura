from __future__ import annotations

import tempfile
from pathlib import Path

from .asr_coordinator import AsrProcessingResult, ReferenceAsrCoordinator
from .media_normalizer import ReferenceMediaNormalizer
from .models import ReferenceSource


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
    ) -> None:
        self._inbox = inbox
        self._normalizer = normalizer
        self._coordinator = coordinator

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return await self._inbox.list_sources()

    async def process_source(
        self,
        source: ReferenceSource,
        *,
        language: str | None = "ja",
        retry: bool = False,
    ) -> AsrProcessingResult:
        with tempfile.TemporaryDirectory(prefix="yura-reference-") as work_dir:
            work_path = Path(work_dir)
            media_path = await self._inbox.materialize(source, work_path)
            audio_path = await self._normalizer.extract_audio(media_path, work_path)
            return await self._coordinator.process(
                source,
                audio_path,
                language=language,
                retry=retry,
            )
