"""Temporary one-way bridge from Streaming public events to Core events.

This compatibility mapper is replaced in J and removed with the legacy integration
in K. A reverse Core-to-Subsystem mapper is intentionally not provided.
"""

from app.domain.events import AgentEvent, AgentEventType
from app.domain.trace_context import TraceContext
from app.integrations.streaming.events import (
    StreamingEventEnvelope,
    StreamingEventType,
)


def comment_event_to_agent_event(event: StreamingEventEnvelope) -> AgentEvent:
    if event.event_type is not StreamingEventType.COMMENT_RECEIVED:
        raise ValueError("streaming.event.not_comment")
    trace = TraceContext(
        trace_id=event.correlation_id or "",
        source_event_id=event.event_id,
    )
    priority = event.payload.get("normalized_priority", 0)
    return AgentEvent(
        event_type=AgentEventType.YOUTUBE_COMMENT,
        payload=dict(event.payload),
        priority=priority if isinstance(priority, int) else 0,
        occurred_at=event.occurred_at,
        event_id=event.event_id,
        trace_context=trace,
    )
