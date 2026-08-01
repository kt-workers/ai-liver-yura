"""Core-facing Streaming Gateway backed by a transport-neutral client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.integrations.streaming.client import StreamingClient
from app.integrations.streaming.connection_state import (
    StreamingConnectionState,
    StreamingConnectionTracker,
)
from app.integrations.streaming.contracts import (
    StreamingCapabilities,
    StreamingCursor,
    StreamingHealth,
    StreamingStatus,
)
from app.integrations.streaming.dependency_health import StreamingDependencyHealth
from app.integrations.streaming.errors import (
    StreamingErrorCode,
    StreamingTransportError,
)
from app.integrations.streaming.events import StreamingEventEnvelope
from app.integrations.streaming.operations import (
    StreamingOperationRequest,
    StreamingOperationResult,
)
from app.integrations.streaming.versioning import (
    CURRENT_STREAMING_API_VERSION,
    is_streaming_api_compatible,
)

T = TypeVar("T")


class StreamingGateway:
    def __init__(self, client: StreamingClient, *, timeout_seconds: float = 5.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._client = client
        self._timeout_seconds = timeout_seconds
        self.connection = StreamingConnectionTracker()
        self._closed = False

    async def connect(self) -> None:
        self._ensure_open()
        self.connection.transition(StreamingConnectionState.CONNECTING)
        try:
            version = await self._wait(self._client.get_api_version())
            if not is_streaming_api_compatible(CURRENT_STREAMING_API_VERSION, version):
                self.connection.transition(
                    StreamingConnectionState.UNAVAILABLE,
                    failure_code="streaming.api_version.incompatible",
                    retryable=False,
                    api_version=version,
                )
                raise StreamingTransportError(
                    code=self._version_error_code(),
                    message="incompatible streaming API version",
                    retryable=False,
                )
            self.connection.transition(
                StreamingConnectionState.CONNECTED,
                api_version=version,
            )
        except (TimeoutError, asyncio.TimeoutError) as error:
            if self.connection.snapshot.state is StreamingConnectionState.CONNECTING:
                self.connection.transition(
                    StreamingConnectionState.UNAVAILABLE,
                    failure_code="streaming.timeout",
                    retryable=True,
                )
            raise StreamingTransportError(
                StreamingErrorCode.TIMEOUT,
                "streaming connection timed out",
                retryable=True,
            ) from error
        except OSError as error:
            self.connection.transition(
                StreamingConnectionState.UNAVAILABLE,
                failure_code="streaming.unavailable",
                retryable=True,
            )
            raise StreamingTransportError(
                StreamingErrorCode.UNAVAILABLE,
                "streaming subsystem is unavailable",
                retryable=True,
            ) from error
        except StreamingTransportError:
            if self.connection.snapshot.state is StreamingConnectionState.CONNECTING:
                self.connection.transition(
                    StreamingConnectionState.UNAVAILABLE,
                    failure_code="streaming.connection.failed",
                    retryable=True,
                )
            raise

    async def get_status(self) -> StreamingStatus:
        return await self._call(self._client.get_status)

    async def get_health(self) -> StreamingHealth:
        return await self._call(self._client.get_health)

    async def get_capabilities(self) -> StreamingCapabilities:
        return await self._call(self._client.get_capabilities)

    async def list_dependency_health(self) -> tuple[StreamingDependencyHealth, ...]:
        return await self._call(self._client.list_dependency_health)

    async def execute(
        self, request: StreamingOperationRequest
    ) -> StreamingOperationResult:
        return await self._call(lambda: self._client.execute(request))

    async def read_events(
        self, after: StreamingCursor | None = None
    ) -> tuple[StreamingEventEnvelope, ...]:
        events = tuple(await self._call(lambda: self._client.read_events(after)))
        if events:
            cursor = events[-1].cursor
            self.connection.transition(
                StreamingConnectionState.CONNECTED,
                cursor=cursor.value if cursor else events[-1].event_id,
            )
        return events

    async def close(self) -> None:
        if self._closed:
            return
        self.connection.transition(StreamingConnectionState.CLOSING)
        self._closed = True
        await self._client.close()
        self.connection.transition(StreamingConnectionState.DISCONNECTED)

    async def _call(self, operation: Callable[[], Awaitable[T]]) -> T:
        self._ensure_open()
        if self.connection.snapshot.state in {
            StreamingConnectionState.DISCONNECTED,
            StreamingConnectionState.UNAVAILABLE,
        }:
            await self.connect()
        try:
            value = await self._wait(operation())
        except asyncio.CancelledError:
            raise
        except (TimeoutError, asyncio.TimeoutError) as error:
            self.connection.transition(
                StreamingConnectionState.DEGRADED,
                failure_code="streaming.timeout",
                retryable=True,
            )
            raise StreamingTransportError(
                code=StreamingErrorCode.TIMEOUT,
                message="streaming request timed out",
                retryable=True,
            ) from error
        except (OSError, StreamingTransportError) as error:
            self.connection.transition(
                StreamingConnectionState.DEGRADED,
                failure_code=getattr(error, "code", "streaming.unavailable").value
                if hasattr(getattr(error, "code", None), "value")
                else "streaming.unavailable",
                retryable=bool(getattr(error, "retryable", True)),
            )
            raise
        self.connection.transition(StreamingConnectionState.CONNECTED)
        return value

    async def _wait(self, operation: Awaitable[T]) -> T:
        return await asyncio.wait_for(operation, timeout=self._timeout_seconds)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("streaming gateway is closed")

    @staticmethod
    def _version_error_code() -> StreamingErrorCode:
        return StreamingErrorCode.UNAVAILABLE
