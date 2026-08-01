"""Internal comment ingress and public Streaming Event conversion."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import uuid4

from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingEventEnvelope,
    StreamingEventType,
)


@dataclass(frozen=True, slots=True)
class StreamingCommentIngressEvent:
    event_type: str
    payload: Mapping[str, object]
    priority: int = 0
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid4()))
    discardable: bool = False
    replace_key: str | None = None
    trace_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_public_event(self) -> StreamingEventEnvelope:
        return StreamingEventEnvelope(
            event_id=self.event_id,
            event_type=StreamingEventType.COMMENT_RECEIVED,
            occurred_at=self.occurred_at,
            api_version=CURRENT_STREAMING_API_VERSION,
            payload=self.payload,
            correlation_id=self.trace_id,
        )


CommentIngressSink = Callable[[StreamingCommentIngressEvent], Awaitable[None]]
PublicCommentEventSink = Callable[[StreamingEventEnvelope], Awaitable[None]]
