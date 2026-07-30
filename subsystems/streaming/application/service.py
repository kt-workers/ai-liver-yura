"""Application Service for the Streaming Subsystem process shell."""

from collections.abc import Sequence

from app.integrations.streaming import (
    StreamingCapabilities,
    StreamingCursor,
    StreamingEventEnvelope,
    StreamingHealth,
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingStatus,
)
from subsystems.streaming.application.ports import StreamingRuntime


class StreamingSubsystemService:
    """Coordinate public use cases through an internal runtime port."""

    def __init__(self, runtime: StreamingRuntime) -> None:
        self._runtime = runtime

    async def get_status(self) -> StreamingStatus:
        return await self._runtime.get_status()

    async def get_health(self) -> StreamingHealth:
        return await self._runtime.get_health()

    async def get_capabilities(self) -> StreamingCapabilities:
        return await self._runtime.get_capabilities()

    async def execute_operation(
        self,
        request: StreamingOperationRequest,
    ) -> StreamingOperationResult:
        return await self._runtime.execute_operation(request)

    async def read_events(
        self,
        after: StreamingCursor | None = None,
    ) -> Sequence[StreamingEventEnvelope]:
        return await self._runtime.read_events(after)
