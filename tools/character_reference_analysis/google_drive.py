from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import google.auth
import httplib2
from google.auth.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.http import HttpRequest, MediaIoBaseDownload, MediaIoBaseUpload

from .manifest import ReferenceAnalysisManifest
from .models import ReferenceSource, ReferenceSourceKind, Transcript
from .progress import ProgressCallback, report_progress

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_DRIVE_SSL_MAX_ATTEMPTS = 3
_DRIVE_SSL_RETRY_BASE_SECONDS = 0.25
_T = TypeVar("_T")


def _call_with_ssl_retry(operation: Callable[[], _T]) -> _T:
    """Retry a complete Drive operation after transient TLS record failures."""

    for attempt in range(_DRIVE_SSL_MAX_ATTEMPTS):
        try:
            return operation()
        except ssl.SSLError:
            if attempt >= _DRIVE_SSL_MAX_ATTEMPTS - 1:
                raise
            time.sleep(_DRIVE_SSL_RETRY_BASE_SECONDS * (2**attempt))
    raise AssertionError("unreachable")


def build_google_drive_credentials(
    *,
    service_account_json_env: str = "YURA_REFERENCE_GOOGLE_SERVICE_ACCOUNT_JSON",
    oauth_client_id_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_ID",
    oauth_client_secret_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_SECRET",
    oauth_refresh_token_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_REFRESH_TOKEN",
) -> Credentials:
    """Build Drive credentials without storing secrets in the repository."""

    client_id = os.environ.get(oauth_client_id_env, "").strip()
    client_secret = os.environ.get(oauth_client_secret_env, "").strip()
    refresh_token = os.environ.get(oauth_refresh_token_env, "").strip()
    if client_id and client_secret and refresh_token:
        return user_credentials.Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=_TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[_DRIVE_SCOPE],
        )

    raw_service_account = os.environ.get(service_account_json_env)
    if raw_service_account:
        info = json.loads(raw_service_account)
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=[_DRIVE_SCOPE],
        )

    credentials, _ = google.auth.default(scopes=[_DRIVE_SCOPE])
    return credentials


def build_google_drive_service(
    *,
    service_account_json_env: str = "YURA_REFERENCE_GOOGLE_SERVICE_ACCOUNT_JSON",
    oauth_client_id_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_ID",
    oauth_client_secret_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_SECRET",
    oauth_refresh_token_env: str = "YURA_REFERENCE_GOOGLE_OAUTH_REFRESH_TOKEN",
) -> Any:
    """Build a Drive v3 service with one HTTP transport per worker thread.

    ``google-api-python-client`` uses ``httplib2.Http`` underneath, and that
    transport is not thread-safe. Character Reference Lab invokes the synchronous
    Drive client through ``asyncio.to_thread()``, so the discovery resource may be
    shared but each worker thread must own its own TLS/HTTP connection state.

    Personal My Drive deployments should normally use the user OAuth refresh-token
    path. A service account remains available for Shared Drive/Workspace deployments.
    """

    credentials = build_google_drive_credentials(
        service_account_json_env=service_account_json_env,
        oauth_client_id_env=oauth_client_id_env,
        oauth_client_secret_env=oauth_client_secret_env,
        oauth_refresh_token_env=oauth_refresh_token_env,
    )
    thread_local = threading.local()

    def authorized_http_for_current_thread() -> AuthorizedHttp:
        authorized_http = getattr(thread_local, "authorized_http", None)
        if authorized_http is None:
            authorized_http = AuthorizedHttp(credentials, http=httplib2.Http())
            thread_local.authorized_http = authorized_http
        return authorized_http

    def build_request(unused_http: Any, *args: Any, **kwargs: Any) -> HttpRequest:
        del unused_http
        return HttpRequest(authorized_http_for_current_thread(), *args, **kwargs)

    bootstrap_http = AuthorizedHttp(credentials, http=httplib2.Http())
    return build(
        "drive",
        "v3",
        http=bootstrap_http,
        requestBuilder=build_request,
        cache_discovery=False,
    )


class GoogleDriveReferenceInbox:
    """Scans one shared Drive folder for reference videos and materializes on demand."""

    def __init__(
        self,
        *,
        service: Any,
        folder_id: str,
        credentials: Credentials | None = None,
    ) -> None:
        self._service = service
        self._folder_id = folder_id
        self._credentials = credentials

    async def list_sources(self) -> tuple[ReferenceSource, ...]:
        return await asyncio.to_thread(self._list_sources_sync)

    def _list_sources_sync(self) -> tuple[ReferenceSource, ...]:
        return _call_with_ssl_retry(self._list_sources_once)

    def _list_sources_once(self) -> tuple[ReferenceSource, ...]:
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
                        "modifiedTime,size,thumbnailLink,hasThumbnail,"
                        "videoMediaMetadata(durationMillis,width,height))"
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

            size_bytes = _optional_non_negative_int(item.get("size"))
            duration_seconds: float | None = None
            video_metadata = item.get("videoMediaMetadata")
            if isinstance(video_metadata, dict):
                duration_millis = _optional_non_negative_int(
                    video_metadata.get("durationMillis")
                )
                if duration_millis is not None:
                    duration_seconds = duration_millis / 1000.0

            sources.append(
                ReferenceSource(
                    reference_id=f"drive:{file_id}",
                    source_kind=ReferenceSourceKind.GOOGLE_DRIVE_VIDEO,
                    source_locator=f"drive-file:{file_id}",
                    display_name=name,
                    content_hash=content_hash,
                    size_bytes=size_bytes,
                    duration_seconds=duration_seconds,
                    thumbnail_available=bool(item.get("thumbnailLink")),
                )
            )
        return tuple(sources)

    async def fetch_thumbnail(
        self,
        source: ReferenceSource,
    ) -> tuple[bytes, str] | None:
        return await asyncio.to_thread(self._fetch_thumbnail_sync, source)

    def _fetch_thumbnail_sync(
        self,
        source: ReferenceSource,
    ) -> tuple[bytes, str] | None:
        return _call_with_ssl_retry(lambda: self._fetch_thumbnail_once(source))

    def _fetch_thumbnail_once(
        self,
        source: ReferenceSource,
    ) -> tuple[bytes, str] | None:
        file_id = _drive_file_id(source.source_locator)
        metadata = (
            self._service.files()
            .get(fileId=file_id, fields="thumbnailLink")
            .execute()
        )
        if not isinstance(metadata, dict):
            return None
        thumbnail_link = metadata.get("thumbnailLink")
        if not isinstance(thumbnail_link, str) or not thumbnail_link:
            return None

        credentials = self._credentials or build_google_drive_credentials()
        with AuthorizedSession(credentials) as session:
            response = session.get(thumbnail_link, timeout=20)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/jpeg")
            content_type = content_type.split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                raise ValueError("Drive thumbnail response is not an image")
            return response.content, content_type

    async def materialize(self, source: ReferenceSource, work_directory: Path) -> Path:
        return await asyncio.to_thread(self._materialize_sync, source, work_directory)

    async def materialize_with_progress(
        self,
        source: ReferenceSource,
        work_directory: Path,
        *,
        progress_callback: ProgressCallback,
    ) -> Path:
        loop = asyncio.get_running_loop()

        def notify(fraction: float) -> None:
            bounded = max(0.0, min(1.0, fraction))
            percent = 5 + round(25 * bounded)
            future = asyncio.run_coroutine_threadsafe(
                report_progress(progress_callback, "downloading_video", percent),
                loop,
            )
            future.result()

        return await asyncio.to_thread(
            self._materialize_sync,
            source,
            work_directory,
            notify,
        )

    def _materialize_sync(
        self,
        source: ReferenceSource,
        work_directory: Path,
        progress_callback: Callable[[float], None] | None = None,
    ) -> Path:
        highest_fraction = 0.0

        def monotonic_progress(fraction: float) -> None:
            nonlocal highest_fraction
            highest_fraction = max(highest_fraction, max(0.0, min(1.0, fraction)))
            if progress_callback is not None:
                progress_callback(highest_fraction)

        return _call_with_ssl_retry(
            lambda: self._materialize_once(
                source,
                work_directory,
                monotonic_progress if progress_callback is not None else None,
            )
        )

    def _materialize_once(
        self,
        source: ReferenceSource,
        work_directory: Path,
        progress_callback: Callable[[float], None] | None = None,
    ) -> Path:
        file_id = _drive_file_id(source.source_locator)
        work_directory.mkdir(parents=True, exist_ok=True)
        destination = work_directory / Path(source.display_name).name
        request = self._service.files().get_media(fileId=file_id)
        with destination.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if progress_callback is not None and status is not None:
                    progress_callback(float(status.progress()))
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
        return _call_with_ssl_retry(lambda: self._load_manifest_once(revision_key))

    def _load_manifest_once(
        self, revision_key: str
    ) -> ReferenceAnalysisManifest | None:
        file_id = self._find_result_file_once(revision_key, "manifest")
        if file_id is None:
            return None
        payload = json.loads(self._download_text_once(file_id))
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
        return _call_with_ssl_retry(
            lambda: self._find_result_file_once(revision_key, result_kind)
        )

    def _find_result_file_once(
        self, revision_key: str, result_kind: str
    ) -> str | None:
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
        _call_with_ssl_retry(
            lambda: self._upsert_text_once(
                revision_key,
                result_kind,
                text,
                mime_type,
            )
        )

    def _upsert_text_once(
        self,
        revision_key: str,
        result_kind: str,
        text: str,
        mime_type: str,
    ) -> None:
        existing_file_id = self._find_result_file_once(revision_key, result_kind)
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
        body = {
            "name": name,
            "parents": [self._folder_id],
            "appProperties": {
                "yura_revision_key": revision_key,
                "yura_result_kind": result_kind,
                "yura_reference_usage": "reference_only",
            },
        }
        (
            self._service.files()
            .create(
                body=body,
                media_body=media,
                fields="id",
            )
            .execute()
        )

    def _download_text(self, file_id: str) -> str:
        return _call_with_ssl_retry(lambda: self._download_text_once(file_id))

    def _download_text_once(self, file_id: str) -> str:
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
        raise ValueError("Drive source locator must start with drive-file:")
    file_id = source_locator[len(prefix) :]
    if not file_id:
        raise ValueError("Drive source locator did not contain a file ID")
    return file_id


def _optional_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
