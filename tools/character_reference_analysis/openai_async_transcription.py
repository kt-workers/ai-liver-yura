from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx

from .models import Transcript
from .openai_transcription import OpenAITranscriptionBackend, OpenAITranscriptionError


class OpenAIAsyncTranscriptionBackend(OpenAITranscriptionBackend):
    """Cancelable OpenAI transcription backend with a strict wall-clock timeout."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini-transcribe",
        api_key_env: str = "OPENAI_API_KEY",
        timeout_seconds: float = 90.0,
        base_url: str = "https://api.openai.com/v1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        super().__init__(
            model=model,
            api_key_env=api_key_env,
            timeout_seconds=timeout_seconds,
            base_url=base_url,
        )
        self._total_timeout_seconds = timeout_seconds
        self._transport = transport

    async def transcribe(
        self,
        media_path: Path,
        *,
        reference_id: str,
        language: str | None = "ja",
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

        async def request_once() -> httpx.Response:
            timeout = httpx.Timeout(self._total_timeout_seconds)
            async with httpx.AsyncClient(
                timeout=timeout,
                transport=self._transport,
            ) as client:
                return await client.post(
                    f"{self._base_url}/audio/transcriptions",
                    content=body,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": content_type,
                    },
                )

        try:
            response = await asyncio.wait_for(
                request_once(),
                timeout=self._total_timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            raise OpenAITranscriptionError(
                "OpenAI transcription timed out after "
                f"{self._total_timeout_seconds:g} seconds"
            ) from error
        except httpx.HTTPError as error:
            raise OpenAITranscriptionError(
                f"OpenAI transcription request failed: {error}"
            ) from error

        if response.is_error:
            detail = response.text
            raise OpenAITranscriptionError(
                f"OpenAI transcription failed with HTTP {response.status_code}: {detail}"
            )

        try:
            payload = response.json()
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
