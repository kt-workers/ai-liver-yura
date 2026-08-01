"""One-way mapper from public Streaming events to safe Core events."""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.domain.trace_context import TraceContext
from app.integrations.streaming.events import StreamingEventEnvelope, StreamingEventType

_FORBIDDEN_KEY_PARTS = (
    "access_token",
    "authorization",
    "client_secret",
    "credential",
    "live_chat_id",
    "obs_password",
    "page_token",
    "password",
    "refresh_token",
    "token_path",
)


class StreamingEventMapper:
    """Maps without importing or invoking RuntimeCoordinator."""

    def map(self, event: StreamingEventEnvelope) -> AgentEvent | None:
        if event.event_type is StreamingEventType.COMMENT_RECEIVED:
            return self._comment(event)
        event_type = {
            StreamingEventType.STATUS_CHANGED: AgentEventType.STREAMING_STATUS_CHANGED,
            StreamingEventType.HEALTH_CHANGED: AgentEventType.STREAMING_HEALTH_CHANGED,
            StreamingEventType.CAPABILITIES_CHANGED: (
                AgentEventType.STREAMING_CAPABILITIES_CHANGED
            ),
            StreamingEventType.ERROR_OCCURRED: AgentEventType.STREAMING_ERROR,
        }.get(event.event_type)
        if event_type is None:
            return None
        return AgentEvent(
            event_type=event_type,
            payload=_safe_mapping(event.payload),
            priority=10,
            occurred_at=event.occurred_at,
            event_id=event.event_id,
            authority=InputAuthority.SYSTEM,
            trace_context=self._trace(event),
        )

    def _comment(self, event: StreamingEventEnvelope) -> AgentEvent:
        raw_comment = event.payload.get("comment", event.payload)
        comment = raw_comment if isinstance(raw_comment, Mapping) else {}
        text = comment.get("text", "")
        payload = _safe_mapping(comment)
        payload.update(
            {
                "text": text if isinstance(text, str) else "",
                "source": "streaming_subsystem",
                "streaming_event_id": event.event_id,
            }
        )
        priority = comment.get("normalized_priority", event.payload.get("normalized_priority", 0))
        return AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload=payload,
            priority=priority if isinstance(priority, int) else 0,
            occurred_at=event.occurred_at,
            event_id=event.event_id,
            authority=InputAuthority.VIEWER,
            trace_context=self._trace(event),
        )

    @staticmethod
    def _trace(event: StreamingEventEnvelope) -> TraceContext:
        return TraceContext(
            trace_id=event.correlation_id or "",
            source_event_id=event.event_id,
        )


def _safe_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _safe_value(item)
        for key, item in value.items()
        if not any(part in key.lower().replace("-", "_") for part in _FORBIDDEN_KEY_PARTS)
    }


def _safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
