"""Internal runtime port implemented by Fake and future adapters."""

from collections.abc import Sequence
from typing import Protocol

from app.integrations.streaming import (
    StreamingCapabilities,
    StreamingCursor,
    StreamingEventEnvelope,
    StreamingHealth,
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingStatus,
)


class StreamingRuntime(Protocol):
    """Runtime behavior required by the Application Service."""

    async def get_status(self) -> StreamingStatus:
        """Return the normalized runtime status."""
        ...

    async def get_health(self) -> StreamingHealth:
        """Return normalized runtime health."""
        ...

    async def get_capabilities(self) -> StreamingCapabilities:
        """Return currently available public capabilities."""
        ...

    async def execute_operation(
        self,
        request: StreamingOperationRequest,
    ) -> StreamingOperationResult:
        """Execute a public operation without raising for normal rejection."""
        ...

    async def read_events(
        self,
        after: StreamingCursor | None = None,
    ) -> Sequence[StreamingEventEnvelope]:
        """Read retained Events after an optional opaque cursor."""
        ...
