"""Test and embedded-process adapter for the Streaming public API."""

from __future__ import annotations

from collections.abc import Sequence

from app.integrations.streaming.contracts import (
    StreamingCapabilities,
    StreamingCursor,
    StreamingHealth,
    StreamingStatus,
)
from app.integrations.streaming.dependency_health import StreamingDependencyHealth
from app.integrations.streaming.events import StreamingEventEnvelope
from app.integrations.streaming.operations import (
    StreamingOperationRequest,
    StreamingOperationResult,
)
from app.integrations.streaming.versioning import (
    CURRENT_STREAMING_API_VERSION,
    StreamingApiVersion,
)


class InProcessStreamingClient:
    """Structural adapter; the wrapped object is not imported from Subsystem."""

    def __init__(self, api: object) -> None:
        self._api = api
        self._closed = False

    async def get_api_version(self) -> StreamingApiVersion:
        return CURRENT_STREAMING_API_VERSION

    async def get_status(self) -> StreamingStatus:
        return await self._call("get_status")

    async def get_health(self) -> StreamingHealth:
        return await self._call("get_health")

    async def get_capabilities(self) -> StreamingCapabilities:
        return await self._call("get_capabilities")

    async def list_dependency_health(self) -> tuple[StreamingDependencyHealth, ...]:
        return tuple(await self._call("list_dependency_health"))

    async def execute(
        self, request: StreamingOperationRequest
    ) -> StreamingOperationResult:
        return await self._api.execute_operation(request)  # type: ignore[attr-defined]

    async def read_events(
        self, after: StreamingCursor | None = None
    ) -> Sequence[StreamingEventEnvelope]:
        return await self._api.read_events(after)  # type: ignore[attr-defined]

    async def close(self) -> None:
        self._closed = True

    async def _call(self, name: str):
        if self._closed:
            raise RuntimeError("streaming client is closed")
        return await getattr(self._api, name)()
