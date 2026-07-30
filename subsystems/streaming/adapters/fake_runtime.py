"""Deterministic in-memory runtime with no external I/O."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingCapabilities,
    StreamingCapability,
    StreamingCursor,
    StreamingError,
    StreamingErrorCode,
    StreamingEventEnvelope,
    StreamingEventType,
    StreamingHealth,
    StreamingIdempotencyKey,
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingOperationType,
    StreamingStatus,
)
from subsystems.streaming.domain import StreamingSubsystemState

_CAPABILITIES = StreamingCapabilities(
    values=frozenset(
        {
            StreamingCapability.PREPARE,
            StreamingCapability.START,
            StreamingCapability.STOP,
            StreamingCapability.PUBLISH_STATUS,
        }
    )
)


@dataclass(frozen=True, slots=True)
class _IdempotencyRecord:
    operation_type: StreamingOperationType
    payload: Mapping[str, object]
    result: StreamingOperationResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeStreamingRuntime:
    """In-memory implementation for process and contract verification."""

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._state = StreamingSubsystemState()
        self._events: list[StreamingEventEnvelope] = []
        self._cursor_positions: dict[StreamingCursor, int] = {}
        self._idempotency: dict[StreamingIdempotencyKey, _IdempotencyRecord] = {}
        self._next_sequence = 1

    async def get_status(self) -> StreamingStatus:
        return self._state.status

    async def get_health(self) -> StreamingHealth:
        return StreamingHealth(
            status=self._state.status,
            healthy=True,
            checked_at=self._clock(),
            components={"runtime": True},
        )

    async def get_capabilities(self) -> StreamingCapabilities:
        return _CAPABILITIES

    async def execute_operation(
        self,
        request: StreamingOperationRequest,
    ) -> StreamingOperationResult:
        replay = self._replay_or_conflict(request)
        if replay is not None:
            return replay

        previous_status = self._state.status
        next_state = self._state.transition(request.operation_type)
        if next_state is None:
            result = self._conflict_result(request, previous_status)
            self._emit_error(request, result)
        else:
            self._state = next_state
            result = StreamingOperationResult(
                operation_id=request.operation_id,
                accepted=True,
                status=next_state.status,
            )
            self._emit_status_changed(
                request,
                previous_status=previous_status,
                status=next_state.status,
            )
            self._emit_operation_completed(request, result)

        self._remember(request, result)
        return result

    async def read_events(
        self,
        after: StreamingCursor | None = None,
    ) -> Sequence[StreamingEventEnvelope]:
        if after is None:
            return tuple(self._events)
        position = self._cursor_positions.get(after)
        if position is None:
            return ()
        return tuple(self._events[position:])

    def _replay_or_conflict(
        self,
        request: StreamingOperationRequest,
    ) -> StreamingOperationResult | None:
        key = request.idempotency_key
        if key is None:
            return None
        record = self._idempotency.get(key)
        if record is None:
            return None
        if (
            record.operation_type == request.operation_type
            and record.payload == request.payload
        ):
            return record.result
        return self._conflict_result(request, self._state.status)

    def _remember(
        self,
        request: StreamingOperationRequest,
        result: StreamingOperationResult,
    ) -> None:
        key = request.idempotency_key
        if key is None:
            return
        self._idempotency[key] = _IdempotencyRecord(
            operation_type=request.operation_type,
            payload=dict(request.payload),
            result=result,
        )

    @staticmethod
    def _conflict_result(
        request: StreamingOperationRequest,
        status: StreamingStatus,
    ) -> StreamingOperationResult:
        return StreamingOperationResult(
            operation_id=request.operation_id,
            accepted=False,
            status=status,
            error=StreamingError(
                code=StreamingErrorCode.CONFLICT,
                message="operation_not_allowed",
                retryable=False,
            ),
        )

    def _emit_status_changed(
        self,
        request: StreamingOperationRequest,
        *,
        previous_status: StreamingStatus,
        status: StreamingStatus,
    ) -> None:
        self._emit(
            StreamingEventType.STATUS_CHANGED,
            {
                "previous_status": previous_status.value,
                "status": status.value,
            },
            correlation_id=request.correlation_id,
        )

    def _emit_operation_completed(
        self,
        request: StreamingOperationRequest,
        result: StreamingOperationResult,
    ) -> None:
        self._emit(
            StreamingEventType.OPERATION_COMPLETED,
            {
                "operation_id": result.operation_id,
                "accepted": result.accepted,
                "status": result.status.value,
            },
            correlation_id=request.correlation_id,
        )

    def _emit_error(
        self,
        request: StreamingOperationRequest,
        result: StreamingOperationResult,
    ) -> None:
        error_code = (
            result.error.code.value
            if result.error is not None
            else StreamingErrorCode.UNKNOWN.value
        )
        self._emit(
            StreamingEventType.ERROR_OCCURRED,
            {
                "operation_id": result.operation_id,
                "error_code": error_code,
                "status": result.status.value,
            },
            correlation_id=request.correlation_id,
        )

    def _emit(
        self,
        event_type: StreamingEventType,
        payload: Mapping[str, object],
        *,
        correlation_id: str | None,
    ) -> None:
        sequence = self._next_sequence
        self._next_sequence += 1
        cursor = StreamingCursor(f"event-cursor-{sequence}")
        event = StreamingEventEnvelope(
            event_id=f"event-{sequence}",
            event_type=event_type,
            occurred_at=self._clock(),
            api_version=CURRENT_STREAMING_API_VERSION,
            payload=payload,
            correlation_id=correlation_id,
            sequence=sequence,
            cursor=cursor,
        )
        self._events.append(event)
        self._cursor_positions[cursor] = len(self._events)
