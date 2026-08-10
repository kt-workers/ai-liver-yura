from __future__ import annotations

import asyncio
from typing import Any

from .google_drive import GoogleDriveReferenceResultStore


class RecoverableGoogleDriveReferenceResultStore(GoogleDriveReferenceResultStore):
    """Drive result store with recovery checks for partially persisted ASR runs."""

    def __init__(self, *, service: Any, folder_id: str) -> None:
        super().__init__(service=service, folder_id=folder_id)

    async def has_transcript(self, revision_key: str) -> bool:
        return await asyncio.to_thread(
            lambda: self._find_result_file(revision_key, "transcript_json") is not None
        )
