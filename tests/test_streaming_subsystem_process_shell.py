from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.integrations.streaming import (
    StreamingCapability,
    StreamingErrorCode,
    StreamingEventType,
    StreamingIdempotencyKey,
    StreamingOperationRequest,
    StreamingOperationType,
    StreamingStatus,
)
from subsystems.streaming import build_streaming_subsystem

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _operation(
    operation_id: str,
    operation_type: StreamingOperationType,
    *,
    payload: dict[str, object] | None = None,
    idempotency_key: StreamingIdempotencyKey | None = None,
    correlation_id: str | None = None,
) -> StreamingOperationRequest:
    return StreamingOperationRequest(
        operation_id=operation_id,
        operation_type=operation_type,
        payload=payload or {},
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


@pytest.mark.asyncio
async def test_process_shell_starts_idle_healthy_and_with_fixed_capabilities() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)

    assert await api.get_status() is StreamingStatus.IDLE

    health = await api.get_health()
    assert health.status is StreamingStatus.IDLE
    assert health.healthy is True
    assert health.checked_at is NOW
    assert health.components == {"runtime": True}

    capabilities = await api.get_capabilities()
    assert capabilities.values == frozenset(
        {
            StreamingCapability.PREPARE,
            StreamingCapability.START,
            StreamingCapability.STOP,
            StreamingCapability.PUBLISH_STATUS,
        }
    )


@pytest.mark.asyncio
async def test_fake_runtime_supports_minimal_prepare_start_stop_lifecycle() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)

    prepare = await api.execute_operation(
        _operation("operation-1", StreamingOperationType.PREPARE)
    )
    start = await api.execute_operation(
        _operation("operation-2", StreamingOperationType.START)
    )
    stop = await api.execute_operation(
        _operation("operation-3", StreamingOperationType.STOP)
    )

    assert prepare.accepted is True
    assert prepare.status is StreamingStatus.READY
    assert start.accepted is True
    assert start.status is StreamingStatus.LIVE
    assert stop.accepted is True
    assert stop.status is StreamingStatus.ENDED
    assert await api.get_status() is StreamingStatus.ENDED


@pytest.mark.asyncio
async def test_invalid_operation_returns_stable_error_instead_of_raising() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)
    request = _operation("operation-1", StreamingOperationType.START)

    result = await api.execute_operation(request)

    assert result.accepted is False
    assert result.status is StreamingStatus.IDLE
    assert result.error is not None
    assert result.error.code is StreamingErrorCode.CONFLICT
    assert result.error.message == "operation_not_allowed"
    assert result.error.retryable is False

    events = await api.read_events()
    assert len(events) == 1
    assert events[0].event_type is StreamingEventType.ERROR_OCCURRED
    assert events[0].payload["error_code"] == StreamingErrorCode.CONFLICT.value


@pytest.mark.asyncio
async def test_same_idempotency_request_replays_without_duplicate_events() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)
    key = StreamingIdempotencyKey("key-1")
    first_request = _operation(
        "operation-1",
        StreamingOperationType.PREPARE,
        payload={"profile": "default"},
        idempotency_key=key,
    )
    replay_request = _operation(
        "operation-2",
        StreamingOperationType.PREPARE,
        payload={"profile": "default"},
        idempotency_key=key,
    )

    first = await api.execute_operation(first_request)
    first_events = await api.read_events()
    replay = await api.execute_operation(replay_request)
    replay_events = await api.read_events()

    assert replay == first
    assert replay.operation_id == "operation-1"
    assert len(first_events) == 2
    assert replay_events == first_events


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_different_payload_is_conflict() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)
    key = StreamingIdempotencyKey("key-1")
    await api.execute_operation(
        _operation(
            "operation-1",
            StreamingOperationType.PREPARE,
            payload={"profile": "default"},
            idempotency_key=key,
        )
    )

    conflict = await api.execute_operation(
        _operation(
            "operation-2",
            StreamingOperationType.PREPARE,
            payload={"profile": "other"},
            idempotency_key=key,
        )
    )

    assert conflict.accepted is False
    assert conflict.status is StreamingStatus.READY
    assert conflict.error is not None
    assert conflict.error.code is StreamingErrorCode.CONFLICT
    assert (await api.read_events())[-1].event_type is StreamingEventType.ERROR_OCCURRED


@pytest.mark.asyncio
async def test_events_have_monotonic_sequence_cursor_and_non_destructive_read() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)
    await api.execute_operation(
        _operation(
            "operation-1",
            StreamingOperationType.PREPARE,
            correlation_id="correlation-1",
        )
    )
    await api.execute_operation(
        _operation(
            "operation-2",
            StreamingOperationType.START,
            correlation_id="correlation-1",
        )
    )

    events = await api.read_events()

    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert all(event.cursor is not None for event in events)
    assert all(event.occurred_at is NOW for event in events)
    assert all(event.correlation_id == "correlation-1" for event in events)
    assert [event.event_type for event in events] == [
        StreamingEventType.STATUS_CHANGED,
        StreamingEventType.OPERATION_COMPLETED,
        StreamingEventType.STATUS_CHANGED,
        StreamingEventType.OPERATION_COMPLETED,
    ]

    first_cursor = events[0].cursor
    assert first_cursor is not None
    assert await api.read_events(first_cursor) == events[1:]
    assert await api.read_events() == events


@pytest.mark.asyncio
async def test_unknown_cursor_returns_no_events() -> None:
    api = build_streaming_subsystem(clock=lambda: NOW)
    await api.execute_operation(
        _operation("operation-1", StreamingOperationType.PREPARE)
    )

    from app.integrations.streaming import StreamingCursor

    assert await api.read_events(StreamingCursor("unknown")) == ()


@pytest.mark.asyncio
async def test_composition_roots_do_not_share_global_state() -> None:
    first = build_streaming_subsystem(clock=lambda: NOW)
    second = build_streaming_subsystem(clock=lambda: NOW)

    await first.execute_operation(
        _operation("operation-1", StreamingOperationType.PREPARE)
    )

    assert await first.get_status() is StreamingStatus.READY
    assert await second.get_status() is StreamingStatus.IDLE
    assert await second.read_events() == ()
