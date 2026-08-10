from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import Transcript


class TranscriptionBackend(Protocol):
    """Provider-independent Japanese ASR boundary for reference analysis."""

    async def transcribe(
        self,
        media_path: Path,
        *,
        reference_id: str,
        language: str | None = "ja",
    ) -> Transcript:
        """Transcribe one temporary/localized media file into the common DTO."""
