from __future__ import annotations

import operator
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone

import pytest

from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingCapabilities,
    StreamingCapability,
    StreamingComment,
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

NOW = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)


def test_public_enum_values_are_stable() -> None:
    assert {status.value for status in StreamingStatus} == {
        "disconnected",
        "unavailable",
        "idle",
        "preparing",
        "ready",
        "starting",
        "live",
        "stopping",
        "ended",
        "degraded",
        "error",
    }
    assert {capability.value for capability in StreamingCapability} == {
        "prepare",
        "start",
        "stop",
        "receive_comments",
        "control_scene",
        "publish_status",
        "tts_available",
        "avatar_available",
    }
    assert {operation.value for operation in StreamingOperationType} == {
        "prepare",
        "start",
        "stop",
        "emergency_stop",
    }
    assert {event_type.value for event_type in StreamingEventType} == {
        "status_changed",
        "health_changed",
        "capabilities_changed",
        "comment_received",
        "operation_completed",
        "error_occurred",
    }


def test_health_is_frozen_and_defensively_copies_components() -> None:
    components = {"ingest": True}
    health = StreamingHealth(
        status=StreamingStatus.READY,
        healthy=True,
        checked_at=NOW,
        components=components,
    )

    components["ingest"] = False

    assert health.components == {"ingest": True}
    with pytest.raises(TypeError):
        operator.setitem(health.components, "ingest", False)
    with pytest.raises(FrozenInstanceError):
        health.healthy = False


def test_comment_retains_normalized_fields_without_raw_payload() -> None:
    cursor = StreamingCursor("cursor-1")
    comment = StreamingComment(
        comment_id="comment-1",
        author_id="author-1",
        author_display_name="Viewer",
        text="hello",
        published_at=NOW,
        stream_id="stream-1",
        moderation_flags=frozenset({"reviewed"}),
        cursor=cursor,
    )

    assert comment.published_at is NOW
    assert comment.cursor == cursor
    assert comment.moderation_flags == frozenset({"reviewed"})
    assert "raw_payload" not in {field.name for field in fields(StreamingComment)}


def test_capability_snapshot_copies_the_input_set() -> None:
    capabilities = {StreamingCapability.PREPARE}
    snapshot = StreamingCapabilities(values=frozenset(capabilities))

    capabilities.add(StreamingCapability.START)

    assert snapshot.values == frozenset({StreamingCapability.PREPARE})


def test_operation_request_and_result_are_separate_immutable_dtos() -> None:
    request_payload: dict[str, object] = {"title": "example"}
    key = StreamingIdempotencyKey("operation-key-1")
    request = StreamingOperationRequest(
        operation_id="operation-1",
        operation_type=StreamingOperationType.PREPARE,
        payload=request_payload,
        idempotency_key=key,
        correlation_id="correlation-1",
    )
    error = StreamingError(
        code=StreamingErrorCode.NOT_CONNECTED,
        message="not connected",
        retryable=True,
    )
    result = StreamingOperationResult(
        operation_id=request.operation_id,
        accepted=False,
        status=StreamingStatus.DISCONNECTED,
        error=error,
    )

    request_payload["title"] = "changed"

    assert request.payload == {"title": "example"}
    assert request.idempotency_key == key
    assert request.correlation_id == "correlation-1"
    assert result.accepted is False
    assert result.error == error
    with pytest.raises(TypeError):
        operator.setitem(request.payload, "title", "changed")


def test_event_envelope_retains_version_sequence_cursor_and_timestamp() -> None:
    payload: dict[str, object] = {
        "comment_id": "comment-1",
        "text": "hello",
    }
    cursor = StreamingCursor("event-cursor-1")
    event = StreamingEventEnvelope(
        event_id="event-1",
        event_type=StreamingEventType.COMMENT_RECEIVED,
        occurred_at=NOW,
        api_version=CURRENT_STREAMING_API_VERSION,
        payload=payload,
        correlation_id="correlation-1",
        sequence=42,
        cursor=cursor,
    )

    payload["text"] = "changed"

    assert event.occurred_at is NOW
    assert event.api_version == CURRENT_STREAMING_API_VERSION
    assert event.sequence == 42
    assert event.cursor == cursor
    assert event.payload["text"] == "hello"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: StreamingHealth(
            status=StreamingStatus.IDLE,
            healthy=True,
            checked_at=datetime(2026, 7, 31),
        ),
        lambda: StreamingComment(
            comment_id="comment-1",
            author_id="author-1",
            author_display_name="Viewer",
            text="hello",
            published_at=datetime(2026, 7, 31),
        ),
        lambda: StreamingEventEnvelope(
            event_id="event-1",
            event_type=StreamingEventType.STATUS_CHANGED,
            occurred_at=datetime(2026, 7, 31),
            api_version=CURRENT_STREAMING_API_VERSION,
            payload={},
        ),
    ],
)
def test_public_timestamps_must_be_timezone_aware(factory: object) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        factory()
