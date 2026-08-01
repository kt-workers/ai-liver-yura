"""No-I/O Streaming gateway used when the Subsystem is not configured."""

from datetime import datetime, timezone

from app.integrations.streaming.connection_state import StreamingConnectionTracker
from app.integrations.streaming.contracts import (
    StreamingCapabilities,
    StreamingCursor,
    StreamingHealth,
    StreamingStatus,
)
from app.integrations.streaming.dependency_health import StreamingDependencyHealth
from app.integrations.streaming.errors import StreamingError, StreamingErrorCode
from app.integrations.streaming.events import StreamingEventEnvelope
from app.integrations.streaming.operations import (
    StreamingOperationRequest,
    StreamingOperationResult,
)


class NullStreamingGateway:
    """Represents an optional, intentionally disconnected Subsystem."""

    def __init__(self) -> None:
        self.connection = StreamingConnectionTracker()

    async def get_status(self) -> StreamingStatus:
        return StreamingStatus.UNAVAILABLE

    async def get_health(self) -> StreamingHealth:
        return StreamingHealth(
            status=StreamingStatus.UNAVAILABLE,
            healthy=False,
            checked_at=datetime.now(timezone.utc),
            message="streaming subsystem is not connected",
        )

    async def get_capabilities(self) -> StreamingCapabilities:
        return StreamingCapabilities(frozenset())

    async def list_dependency_health(self) -> tuple[StreamingDependencyHealth, ...]:
        return ()

    async def execute(
        self, request: StreamingOperationRequest
    ) -> StreamingOperationResult:
        return StreamingOperationResult(
            operation_id=request.operation_id,
            accepted=False,
            status=StreamingStatus.UNAVAILABLE,
            error=StreamingError(
                code=StreamingErrorCode.NOT_CONNECTED,
                message="streaming subsystem is not connected",
                retryable=True,
            ),
        )

    async def read_events(
        self, after: StreamingCursor | None = None
    ) -> tuple[StreamingEventEnvelope, ...]:
        del after
        return ()

    async def close(self) -> None:
        return None
