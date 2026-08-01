"""HTTP transport for the Streaming Subsystem public API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.integrations.streaming.contracts import (
    StreamingCapabilities,
    StreamingCursor,
    StreamingHealth,
    StreamingStatus,
    normalize_streaming_status,
)
from app.integrations.streaming.dependency_health import StreamingDependencyHealth
from app.integrations.streaming.errors import StreamingErrorCode, StreamingTransportError
from app.integrations.streaming.events import StreamingEventEnvelope
from app.integrations.streaming.operations import (
    StreamingOperationRequest,
    StreamingOperationResult,
)
from app.integrations.streaming.versioning import StreamingApiVersion
from app.integrations.streaming.wire import (
    parse_api_version,
    parse_capabilities,
    parse_dependency,
    parse_event,
    parse_health,
    parse_operation_result,
    to_wire,
)


@dataclass(frozen=True, slots=True)
class StreamingHttpClientConfig:
    base_url: str
    timeout_seconds: float = 5.0
    token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        normalized = self.base_url.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("streaming base_url must use http or https")
        if self.timeout_seconds <= 0:
            raise ValueError("streaming timeout_seconds must be positive")
        object.__setattr__(self, "base_url", normalized)


class HttpStreamingClient:
    def __init__(self, config: StreamingHttpClientConfig) -> None:
        self._config = config
        self._closed = False

    async def get_api_version(self) -> StreamingApiVersion:
        return parse_api_version(await self._request("GET", "/version"))

    async def get_status(self) -> StreamingStatus:
        data = _mapping(await self._request("GET", "/status"))
        value = data.get("status")
        if not isinstance(value, str):
            raise ValueError("streaming response status must be a string")
        return normalize_streaming_status(value)

    async def get_health(self) -> StreamingHealth:
        return parse_health(await self._request("GET", "/health"))

    async def get_capabilities(self) -> StreamingCapabilities:
        return parse_capabilities(await self._request("GET", "/capabilities"))

    async def list_dependency_health(self) -> tuple[StreamingDependencyHealth, ...]:
        data = _mapping(await self._request("GET", "/dependencies/health"))
        items = data.get("items", ())
        if not isinstance(items, list):
            raise ValueError("streaming response items must be a list")
        return tuple(parse_dependency(item) for item in items)

    async def execute(
        self, request: StreamingOperationRequest
    ) -> StreamingOperationResult:
        return parse_operation_result(
            await self._request("POST", "/operations", body=to_wire(request))
        )

    async def read_events(
        self, after: StreamingCursor | None = None
    ) -> Sequence[StreamingEventEnvelope]:
        suffix = f"?after={quote(after.value)}" if after is not None else ""
        data = _mapping(await self._request("GET", f"/events{suffix}"))
        items = data.get("items", ())
        if not isinstance(items, list):
            raise ValueError("streaming response items must be a list")
        return tuple(event for item in items if (event := parse_event(item)) is not None)

    async def close(self) -> None:
        self._closed = True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
    ) -> object:
        if self._closed:
            raise RuntimeError("streaming HTTP client is closed")
        return await asyncio.to_thread(self._request_sync, method, path, body)

    def _request_sync(self, method: str, path: str, body: object | None) -> object:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        request = Request(
            f"{self._config.base_url}/api/v1/integration{path}",
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            code = (
                StreamingErrorCode.INVALID_REQUEST
                if 400 <= error.code < 500
                else StreamingErrorCode.UNAVAILABLE
            )
            raise StreamingTransportError(
                code,
                f"streaming API returned HTTP {error.code}",
                retryable=error.code >= 500,
            ) from error
        except (URLError, TimeoutError) as error:
            raise StreamingTransportError(
                StreamingErrorCode.UNAVAILABLE,
                "streaming API is unavailable",
                retryable=True,
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StreamingTransportError(
                StreamingErrorCode.INTERNAL_ERROR,
                "streaming API returned an invalid response",
                retryable=False,
            ) from error


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("streaming response must contain an object")
    return value
