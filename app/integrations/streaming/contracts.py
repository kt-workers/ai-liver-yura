"""Normalized query DTOs and opaque values for Streaming integration."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType


class StreamingStatus(str, Enum):
    """Normalized subsystem status independent of external adapters."""

    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"
    IDLE = "idle"
    PREPARING = "preparing"
    READY = "ready"
    STARTING = "starting"
    LIVE = "live"
    STOPPING = "stopping"
    ENDED = "ended"
    DEGRADED = "degraded"
    ERROR = "error"


def normalize_streaming_status(value: str) -> StreamingStatus:
    """Normalize an unknown future status to the conservative fallback."""

    try:
        return StreamingStatus(value)
    except ValueError:
        return StreamingStatus.DEGRADED


class StreamingCapability(str, Enum):
    """Operations or feeds available without exposing adapter names."""

    PREPARE = "prepare"
    START = "start"
    STOP = "stop"
    RECEIVE_COMMENTS = "receive_comments"
    CONTROL_SCENE = "control_scene"
    PUBLISH_STATUS = "publish_status"


def normalize_streaming_capabilities(
    values: Iterable[str],
) -> frozenset[StreamingCapability]:
    """Keep known capabilities and safely ignore future values."""

    known_values = {capability.value: capability for capability in StreamingCapability}
    return frozenset(
        known_values[value] for value in values if value in known_values
    )


@dataclass(frozen=True, slots=True)
class StreamingCapabilities:
    """Normalized capability snapshot returned by a Query."""

    values: frozenset[StreamingCapability]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", frozenset(self.values))


@dataclass(frozen=True, slots=True)
class StreamingCursor:
    """Opaque Comment or Event retrieval position."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("cursor must not be empty")


@dataclass(frozen=True, slots=True)
class StreamingIdempotencyKey:
    """Opaque key used to deduplicate an operation."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("idempotency key must not be empty")


@dataclass(frozen=True, slots=True)
class StreamingHealth:
    """Normalized health without external service response objects."""

    status: StreamingStatus
    healthy: bool
    checked_at: datetime
    message: str | None = None
    components: Mapping[str, bool] = MappingProxyType({})

    def __post_init__(self) -> None:
        _require_timezone(self.checked_at, field_name="checked_at")
        object.__setattr__(
            self,
            "components",
            MappingProxyType(dict(self.components)),
        )


@dataclass(frozen=True, slots=True)
class StreamingComment:
    """A normalized comment delivered to Core consumers."""

    comment_id: str
    author_id: str
    author_display_name: str
    text: str
    published_at: datetime
    stream_id: str | None = None
    moderation_flags: frozenset[str] = frozenset()
    cursor: StreamingCursor | None = None

    def __post_init__(self) -> None:
        _require_timezone(self.published_at, field_name="published_at")
        object.__setattr__(
            self,
            "moderation_flags",
            frozenset(self.moderation_flags),
        )


def _require_timezone(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
