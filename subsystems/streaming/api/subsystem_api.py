"""Application facade exposed by the Streaming Subsystem process shell."""

from collections.abc import Sequence

from app.integrations.streaming import (
    DependencyKind,
    StreamingCapabilities,
    StreamingCursor,
    StreamingDependencyHealth,
    StreamingEventEnvelope,
    StreamingHealth,
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingStatus,
)
from subsystems.streaming.application import StreamingSubsystemService
from subsystems.streaming.application.session_components import (
    StreamingSessionComponents,
)


class StreamingSubsystemApi:
    """Transport-independent facade for Query, Command, and Event access."""

    def __init__(
        self,
        service: StreamingSubsystemService,
        *,
        sessions: StreamingSessionComponents | None = None,
    ) -> None:
        self._service = service
        self._sessions = sessions

    @property
    def sessions(self) -> StreamingSessionComponents:
        """Return H application components without coupling callers to Core runtime."""

        if self._sessions is None:
            raise RuntimeError("streaming.sessions.not_configured")
        return self._sessions

    async def get_status(self) -> StreamingStatus:
        return await self._service.get_status()

    async def get_health(self) -> StreamingHealth:
        return await self._service.get_health()

    async def get_capabilities(self) -> StreamingCapabilities:
        return await self._service.get_capabilities()

    async def get_dependency_health(
        self,
        kind: DependencyKind,
    ) -> StreamingDependencyHealth:
        return await self._service.get_dependency_health(kind)

    async def list_dependency_health(
        self,
    ) -> tuple[StreamingDependencyHealth, ...]:
        return await self._service.list_dependency_health()

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
