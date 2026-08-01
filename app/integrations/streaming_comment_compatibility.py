"""Temporary one-way bridge from Streaming public events to Core events.

This compatibility mapper is replaced in J and removed with the legacy integration
in K. A reverse Core-to-Subsystem mapper is intentionally not provided.
"""

from app.domain.events import AgentEvent
from app.integrations.streaming.event_mapper import StreamingEventMapper
from app.integrations.streaming.events import StreamingEventEnvelope


def comment_event_to_agent_event(event: StreamingEventEnvelope) -> AgentEvent:
    mapped = StreamingEventMapper().map(event)
    if mapped is None or mapped.event_type.value != "youtube_comment":
        raise ValueError("streaming.event.not_comment")
    return mapped
