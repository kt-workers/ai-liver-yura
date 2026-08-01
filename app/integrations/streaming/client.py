"""Transport boundary used by the Core Streaming gateway."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

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
from app.integrations.streaming.versioning import StreamingApiVersion


class StreamingClient(Protocol):
    """Transport-neutral client implemented by HTTP and in-process adapters."""

    async def get_api_version(self) -> StreamingApiVersion: ...

    async def get_status(self) -> StreamingStatus: ...

    async def get_health(self) -> StreamingHealth: ...

    async def get_capabilities(self) -> StreamingCapabilities: ...

    async def list_dependency_health(
        self,
    ) -> tuple[StreamingDependencyHealth, ...]: ...

    async def execute(
        self,
        request: StreamingOperationRequest,
    ) -> StreamingOperationResult: ...

    async def read_events(
        self,
        after: StreamingCursor | None = None,
    ) -> Sequence[StreamingEventEnvelope]: ...

    async def close(self) -> None: ...
