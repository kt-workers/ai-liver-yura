from datetime import datetime, timezone

from app.integrations.streaming import StreamingEventType
from subsystems.streaming.ports.comment_events import StreamingCommentIngressEvent


def test_comment_event_uses_existing_public_contract() -> None:
    event = StreamingCommentIngressEvent(
        "youtube_comment",
        {"session_id": "session", "message_id": "message", "comment": "hello"},
        occurred_at=datetime.now(timezone.utc),
        trace_id="trace",
    ).to_public_event()
    assert event.event_type is StreamingEventType.COMMENT_RECEIVED
    assert event.correlation_id == "trace"
    assert dict(event.payload)["message_id"] == "message"


def test_public_comment_event_does_not_add_private_adapter_state() -> None:
    event = StreamingCommentIngressEvent(
        "youtube_comment", {"session_id": "session", "comment": "hello"}
    ).to_public_event()
    assert not set(event.payload) & {
        "page_token",
        "live_chat_id",
        "access_token",
        "refresh_token",
        "credential",
    }
