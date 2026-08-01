from datetime import datetime, timezone

from app.domain.events import AgentEventType, InputAuthority
from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingEventEnvelope,
    StreamingEventMapper,
    StreamingEventType,
)


def event(event_type: StreamingEventType, payload: dict[str, object]):
    return StreamingEventEnvelope(
        event_id="event-1",
        event_type=event_type,
        occurred_at=datetime.now(timezone.utc),
        api_version=CURRENT_STREAMING_API_VERSION,
        payload=payload,
    )


def test_comment_is_mapped_to_viewer_input_without_secret_fields() -> None:
    mapped = StreamingEventMapper().map(
        event(
            StreamingEventType.COMMENT_RECEIVED,
            {
                "comment": {
                    "text": "配信コメント",
                    "author_role": "owner",
                    "is_paid": True,
                    "access_token": "must-not-leak",
                    "nested": {"client_secret": "must-not-leak"},
                }
            },
        )
    )
    assert mapped is not None
    assert mapped.event_type is AgentEventType.USER_TEXT
    assert mapped.authority is InputAuthority.VIEWER
    assert mapped.payload["is_paid"] is True
    assert "access_token" not in mapped.payload
    assert mapped.payload["nested"] == {}


def test_status_and_unknown_policy_do_not_touch_runtime() -> None:
    mapped = StreamingEventMapper().map(
        event(StreamingEventType.STATUS_CHANGED, {"status": "live"})
    )
    assert mapped is not None
    assert mapped.event_type is AgentEventType.STREAMING_STATUS_CHANGED
    assert mapped.authority is InputAuthority.SYSTEM
