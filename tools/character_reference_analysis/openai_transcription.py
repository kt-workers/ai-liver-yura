from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import Transcript, TranscriptSegment, TranscriptionMetadata


class OpenAITranscriptionError(RuntimeError):
    """Raised when reference transcription cannot be completed safely."""


class OpenAITranscriptionBackend:
    """OpenAI Audio Transcriptions adapter for reference-only analysis.

    The default diarization model is used because it provides timestamped segments
    and speaker labels in one request. Other supported models are normalized into
    the same Transcript DTO.
    """

    def __init__(
        self,
        *,
        model: str = "gpt-4o-transcribe-diarize",
        api_key_env: str = "OPENAI_API_KEY",
        timeout_seconds: float = 180.0,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url.rstrip("/")

    async def transcribe(
        self,
        media_path: Path,
        *,
        reference_id: str,
        language: str | None = "ja",
    ) -> Transcript:
        return await asyncio.to_thread(
            self._transcribe_sync,
            media_path,
            reference_id,
            language,
        )

    def _transcribe_sync(
        self,
        media_path: Path,
        reference_id: str,
        language: str | None,
    ) -> Transcript:
        if not media_path.is_file():
            raise OpenAITranscriptionError(f"media file not found: {media_path}")
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise OpenAITranscriptionError(
                f"API key environment variable is missing: {self._api_key_env}"
            )

        response_format, fields = self._request_fields(language)
        body, content_type = self._build_multipart(media_path, fields)
        request = urllib.request.Request(
            f"{self._base_url}/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": content_type,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise OpenAITranscriptionError(
                f"OpenAI transcription failed with HTTP {error.code}: {detail}"
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise OpenAITranscriptionError(
                f"OpenAI transcription request failed: {error}"
            ) from error

        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as error:
            raise OpenAITranscriptionError(
                "OpenAI transcription response was not valid JSON"
            ) from error

        if not isinstance(payload, dict):
            raise OpenAITranscriptionError("OpenAI transcription response must be an object")
        return self._parse_response(
            payload,
            reference_id=reference_id,
            requested_language=language,
            response_format=response_format,
        )

    def _request_fields(self, language: str | None) -> tuple[str, list[tuple[str, str]]]:
        fields: list[tuple[str, str]] = [("model", self._model)]
        if language:
            fields.append(("language", language))

        if self._model == "gpt-4o-transcribe-diarize":
            response_format = "diarized_json"
            fields.extend(
                (
                    ("response_format", response_format),
                    ("chunking_strategy", "auto"),
                )
            )
        elif self._model == "whisper-1":
            response_format = "verbose_json"
            fields.extend(
                (
                    ("response_format", response_format),
                    ("timestamp_granularities[]", "segment"),
                )
            )
        else:
            response_format = "json"
            fields.append(("response_format", response_format))
        return response_format, fields

    @staticmethod
    def _build_multipart(
        media_path: Path,
        fields: list[tuple[str, str]],
    ) -> tuple[bytes, str]:
        boundary = f"----yura-reference-{uuid4().hex}"
        chunks: list[bytes] = []
        for name, value in fields:
            chunks.extend(
                (
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                )
            )

        mime_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
        chunks.extend(
            (
                f"--{boundary}\r\n".encode(),
                (
                    'Content-Disposition: form-data; name="file"; '
                    f'filename="{media_path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode(),
                media_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            )
        )
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def _parse_response(
        self,
        payload: dict[str, Any],
        *,
        reference_id: str,
        requested_language: str | None,
        response_format: str,
    ) -> Transcript:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise OpenAITranscriptionError("transcription response did not contain text")

        detected_language = payload.get("language")
        if not isinstance(detected_language, str):
            detected_language = None
        segment_language = requested_language or detected_language
        segments = self._parse_segments(
            payload.get("segments"),
            language=segment_language,
        )
        duration = payload.get("duration")
        if not isinstance(duration, (int, float)):
            duration = None

        return Transcript(
            reference_id=reference_id,
            text=text.strip(),
            segments=segments,
            metadata=TranscriptionMetadata(
                provider="openai",
                model=self._model,
                requested_language=requested_language,
                detected_language=detected_language,
                response_format=response_format,
                source_duration_seconds=float(duration) if duration is not None else None,
            ),
        )

    @staticmethod
    def _parse_segments(
        value: Any,
        *,
        language: str | None,
    ) -> tuple[TranscriptSegment, ...]:
        if not isinstance(value, list):
            return ()
        parsed: list[TranscriptSegment] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            start = item.get("start")
            end = item.get("end")
            speaker = item.get("speaker")
            parsed.append(
                TranscriptSegment(
                    text=text.strip(),
                    start_seconds=float(start) if isinstance(start, (int, float)) else None,
                    end_seconds=float(end) if isinstance(end, (int, float)) else None,
                    language=language,
                    speaker=speaker if isinstance(speaker, str) else None,
                )
            )
        return tuple(parsed)
