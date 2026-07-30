"""Versioned Event Envelope for Streaming notifications."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from app.integrations.streaming.contracts import StreamingCursor
from app.integrations.streaming.versioning import StreamingApiVersion


class StreamingEventType(str, Enum):
    """Normalized events independent of external adapters."""

    STATUS_CHANGED = "status_changed"
    HEALTH_CHANGED = "health_changed"
    CAPABILITIES_CHANGED = "capabilities_changed"
    COMMENT_RECEIVED = "comment_received"
    OPERATION_COMPLETED = "operation_completed"
    ERROR_OCCURRED = "error_occurred"


def parse_streaming_event_type(value: str) -> StreamingEventType | None:
    """Return None when an older consumer receives a future Event type."""

    try:
        return StreamingEventType(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class StreamingEventEnvelope:
    """Common metadata and neutral payload for a Streaming Event."""

    event_id: str
    event_type: StreamingEventType
    occurred_at: datetime
    api_version: StreamingApiVersion
    payload: Mapping[str, object]
    correlation_id: str | None = None
    sequence: int | None = None
    cursor: StreamingCursor | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence must not be negative")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
