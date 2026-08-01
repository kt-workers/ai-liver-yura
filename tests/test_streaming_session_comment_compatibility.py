from datetime import datetime, timezone

from app.domain.events import AgentEventType
from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingEventEnvelope,
    StreamingEventType,
)
from app.integrations.streaming_comment_compatibility import (
    comment_event_to_agent_event,
)
from app.plugins.youtube_streaming.application import StreamLifecycleGate as LegacyGate
from app.plugins.youtube_streaming.domain import StreamSession as LegacySession
from subsystems.streaming.application import StreamLifecycleGate
from subsystems.streaming.domain import StreamSession


def test_legacy_paths_reexport_canonical_symbols() -> None:
    assert LegacySession is StreamSession
    assert LegacyGate is StreamLifecycleGate


def test_public_comment_event_maps_one_way_to_core_event() -> None:
    public = StreamingEventEnvelope(
        event_id="event",
        event_type=StreamingEventType.COMMENT_RECEIVED,
        occurred_at=datetime.now(timezone.utc),
        api_version=CURRENT_STREAMING_API_VERSION,
        payload={"session_id": "session", "comment": "hello"},
        correlation_id="trace",
    )
    core = comment_event_to_agent_event(public)
    assert core.event_type is AgentEventType.YOUTUBE_COMMENT
    assert core.trace_context.trace_id == "trace"
