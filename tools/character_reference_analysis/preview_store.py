from __future__ import annotations

import asyncio
import hashlib
import io
from typing import Any

from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


class GoogleDriveReferencePreviewStore:
    """Persist derived reference-only preview images outside Render ephemeral disk."""

    _RESULT_KIND = "preview_thumbnail"

    def __init__(self, *, service: Any, folder_id: str) -> None:
        self._service = service
        self._folder_id = folder_id

    async def load(
        self,
        revision_key: str,
    ) -> tuple[bytes, str] | None:
        return await asyncio.to_thread(self._load_sync, revision_key)

    async def save(
        self,
        revision_key: str,
        content: bytes,
        media_type: str,
    ) -> None:
        await asyncio.to_thread(
            self._save_sync,
            revision_key,
            content,
            media_type,
        )

    def _load_sync(self, revision_key: str) -> tuple[bytes, str] | None:
        file_id, media_type = self._find(revision_key)
        if file_id is None:
            return None
        request = self._service.files().get_media(fileId=file_id)
        target = io.BytesIO()
        downloader = MediaIoBaseDownload(target, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return target.getvalue(), media_type or "image/jpeg"

    def _save_sync(
        self,
        revision_key: str,
        content: bytes,
        media_type: str,
    ) -> None:
        existing_file_id, _ = self._find(revision_key)
        digest = hashlib.sha256(revision_key.encode("utf-8")).hexdigest()[:16]
        name = f"yura-reference-{digest}-preview.jpg"
        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=media_type,
            resumable=False,
        )
        body = {
            "name": name,
            "appProperties": {
                "yura_revision_key": revision_key,
                "yura_result_kind": self._RESULT_KIND,
                "yura_reference_usage": "reference_only",
            },
        }
        if existing_file_id:
            (
                self._service.files()
                .update(
                    fileId=existing_file_id,
                    body=body,
                    media_body=media,
                    fields="id",
                )
                .execute()
            )
            return
        body["parents"] = [self._folder_id]
        (
            self._service.files()
            .create(
                body=body,
                media_body=media,
                fields="id",
            )
            .execute()
        )

    def _find(self, revision_key: str) -> tuple[str | None, str | None]:
        revision = _escape_drive_query(revision_key)
        folder = _escape_drive_query(self._folder_id)
        kind = self._RESULT_KIND
        query = (
            f"'{folder}' in parents and trashed = false and "
            f"appProperties has {{ key='yura_revision_key' and value='{revision}' }} and "
            f"appProperties has {{ key='yura_result_kind' and value='{kind}' }}"
        )
        response = (
            self._service.files()
            .list(q=query, fields="files(id,mimeType)", pageSize=2)
            .execute()
        )
        files = response.get("files", []) if isinstance(response, dict) else []
        if not files or not isinstance(files[0], dict):
            return None, None
        file_id = files[0].get("id")
        media_type = files[0].get("mimeType")
        return (
            file_id if isinstance(file_id, str) else None,
            media_type if isinstance(media_type, str) else None,
        )


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
