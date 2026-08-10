from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

import google.auth
from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from .manifest import ReferenceAnalysisManifest
from .models import ReferenceSource, ReferenceSourceKind, Transcript

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_google_drive_service(
    *,
    service_account_json_env: str = "YURA_REFERENCE_GOOGLE_SERVICE_ACCOUNT_JSON",
    oauth_client_id_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_ID",
    oauth_client_secret_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_SECRET",
    oauth_refresh_token_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_REFRESH_TOKEN",
) -> Any:
    """Build Drive v3 service without storing credentials in the repository.

    Personal My Drive deployments should normally use the user OAuth refresh-token
    path. A service account remains available for Shared Drive/Workspace deployments.
    """

    client_id = os.environ.get(oauth_client_id_env, "").strip()
    client_secret = os.environ.get(oauth_client_secret_env, "").strip()
    refresh_token = os.environ.get(oauth_refresh_token_env, "").strip()
    if client_id and client_secret and refresh_token:
        credentials = user_credentials.Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=_TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[_DRIVE_SCOPE],
        )
    else:
        raw_service_account = os.environ.get(service_account_json_env)
        if raw_service_account:
            info = json.loads(raw_service_account)
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=[_DRIVE_SCOPE],
            )
        else:
            credentials, _ = google.auth.default(scopes=[_DRIVE_SCOPE])
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


class GoogleDriveReferenceInbox:
    """Scans one shared Drive folder for reference videos and materializes on demand."""

    def __init__(self, *, service: Any, folder_id: str) -> None:
        self._service = service
        self._folder_id = folder_id

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return await asyncio.to_thread(self._list_sources_sync)

    def _list_sources_sync(self) -> tuple[ReferenceSource, ...]:
        files: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            response = (
                self._service.files()
                .list(
                    q=(
                        f"'{_escape_drive_query(self._folder_id)}' in parents "
                        "and trashed = false"
                    ),
                    fields=(
                        "nextPageToken,files(id,name,mimeType,md5Checksum,version,"
                        "modifiedTime,size)"
                    ),
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
            if not isinstance(response, dict):
                break
            batch = response.get("files", [])
            if isinstance(batch, list):
                files.extend(item for item in batch if isinstance(item, dict))
            next_token = response.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token

        sources: list[ReferenceSource] = []
        for item in files:
            mime_type = item.get("mimeType")
            if not isinstance(mime_type, str) or not mime_type.startswith("video/"):
                continue
            file_id = item.get("id")
            name = item.get("name")
            if not isinstance(file_id, str) or not isinstance(name, str):
                continue
            checksum = item.get("md5Checksum")
            version = item.get("version")
            content_hash: str | None
            if isinstance(checksum, str) and checksum:
                content_hash = f"md5:{checksum}"
            elif version is not None:
                content_hash = f"drive-version:{version}"
            else:
                content_hash = None
            sources.append(
                ReferenceSource(
                    reference_id=f"drive:{file_id}",
                    source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
                    source_locator=f"drive-file:{file_id}",
                    display_name=name,
                    content_hash=content_hash,
                )
            )
        return tuple(sources)

    async def materialize(self, source: ReferenceSource, work_directory: Path) -> Path:
        return await asyncio.to_thread(self._materialize_sync, source, work_directory)

    def _materialize_sync(self, source: ReferenceSource, work_directory: Path) -> Path:
        file_id = _drive_file_id(source.source_locator)
        work_directory.mkdir(parents=True, exist_ok=True)
        destination = work_directory / Path(source.display_name).name
        request = self._service.files().get_media(fileId=file_id)
        with destination.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return destination


class GoogleDriveReferenceResultStore:
    """Stores normalized analysis products in Drive, never on Render ephemeral disk."""

    def __init__(self, *, service: Any, folder_id: str) -> None:
        self._service = service
        self._folder_id = folder_id

    async def has_revision(self, revision_key: str) -> bool:
        return await asyncio.to_thread(
            lambda: self._find_result_file(revision_key, "manifest") is not None
        )

    async def load_manifest(
        self, revision_key: str
    ) -> ReferenceAnalysisManifest | None:
        return await asyncio.to_thread(self._load_manifest_sync, revision_key)

    def _load_manifest_sync(
        self, revision_key: str
    ) -> ReferenceAnalysisManifest | None:
        file_id = self._find_result_file(revision_key, "manifest")
        if file_id is None:
            return None
        payload = json.loads(self._download_text(file_id))
        if not isinstance(payload, dict):
            raise ValueError("stored reference manifest must be a JSON object")
        return ReferenceAnalysisManifest.from_dict(payload)

    async def save_manifest(self, manifest: ReferenceAnalysisManifest) -> None:
        await asyncio.to_thread(
            self._upsert_text,
            manifest.revision_key,
            "manifest",
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            "application/json",
        )

    async def save_transcript(self, transcript: Transcript, *, revision_key: str) -> None:
        transcript_json = json.dumps(
            transcript.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
        await asyncio.gather(
            asyncio.to_thread(
                self._upsert_text,
                revision_key,
                "transcript_json",
                transcript_json,
                "application/json",
            ),
            asyncio.to_thread(
                self._upsert_text,
                revision_key,
                "transcript_text",
                transcript.text,
                "text/plain; charset=utf-8",
            ),
        )

    def _find_result_file(self, revision_key: str, result_kind: str) -> str | None:
        revision = _escape_drive_query(revision_key)
        kind = _escape_drive_query(result_kind)
        folder = _escape_drive_query(self._folder_id)
        query = (
            f"'{folder}' in parents and trashed = false and "
            f"appProperties has {{ key='yura_revision_key' and value='{revision}' }} and "
            f"appProperties has {{ key='yura_result_kind' and value='{kind}' }}"
        )
        response = (
            self._service.files()
            .list(q=query, fields="files(id)", pageSize=2)
            .execute()
        )
        files = response.get("files", []) if isinstance(response, dict) else []
        if not files:
            return None
        first = files[0]
        if not isinstance(first, dict):
            return None
        file_id = first.get("id")
        return file_id if isinstance(file_id, str) else None

    def _upsert_text(
        self,
        revision_key: str,
        result_kind: str,
        text: str,
        mime_type: str,
    ) -> None:
        existing_file_id = self._find_result_file(revision_key, result_kind)
        suffix = "txt" if result_kind == "transcript_text" else "json"
        digest = hashlib.sha256(revision_key.encode("utf-8")).hexdigest()[:16]
        name = f"yura-reference-{digest}-{result_kind}.{suffix}"
        media = MediaIoBaseUpload(
            io.BytesIO(text.encode("utf-8")),
            mimetype=mime_type,
            resumable=False,
        )
        if existing_file_id:
            (
                self._service.files()
                .update(
                    fileId=existing_file_id,
                    body={"name": name},
                    media_body=media,
                    fields="id",
                )
                .execute()
            )
            return
        (
            self._service.files()
            .create(
                body={
                    "name": name,
                    "parents": [self._folder_id],
                    "appProperties": {
                        "yura_revision_key": revision_key,
                        "yura_result_kind": result_kind,
                    },
                },
                media_body=media,
                fields="id",
            )
            .execute()
        )

    def _download_text(self, file_id: str) -> str:
        request = self._service.files().get_media(fileId=file_id)
        target = io.BytesIO()
        downloader = MediaIoBaseDownload(target, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return target.getvalue().decode("utf-8")


def _drive_file_id(source_locator: str) -> str:
    prefix = "drive-file:"
    if not source_locator.startswith(prefix):
        raise ValueError("source locator is not a Drive file locator")
    file_id = source_locator[len(prefix) :]
    if not file_id:
        raise ValueError("Drive file locator is missing file id")
    return file_id


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
