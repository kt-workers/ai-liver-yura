"""Application facade exposed by the Streaming Subsystem process shell."""

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
from subsystems.streaming.application import StreamingSubsystemService


class StreamingSubsystemApi:
    """Transport-independent facade for Query, Command, and Event access."""

    def __init__(self, service: StreamingSubsystemService) -> None:
        self._service = service

    async def get_status(self) -> StreamingStatus:
        return await self._service.get_status()

    async def get_health(self) -> StreamingHealth:
        return await self._service.get_health()

    async def get_capabilities(self) -> StreamingCapabilities:
        return await self._service.get_capabilities()

    async def execute_operation(
        self,
        request: StreamingOperationRequest,
    ) -> StreamingOperationResult:
        return await self._service.execute_operation(request)

    async def read_events(
        self,
        after: StreamingCursor | None = None,
    ) -> Sequence[StreamingEventEnvelope]:
        return await self._service.read_events(after)
