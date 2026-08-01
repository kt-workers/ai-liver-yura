"""Command request and result DTOs for Streaming operations."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from app.integrations.streaming.contracts import (
    StreamingIdempotencyKey,
    StreamingStatus,
)
from app.integrations.streaming.errors import StreamingError


class StreamingOperationType(str, Enum):
    """Minimal commands supported by the public boundary."""

    PREPARE = "prepare"
    START = "start"
    STOP = "stop"
    EMERGENCY_STOP = "emergency_stop"


@dataclass(frozen=True, slots=True)
class StreamingOperationRequest:
    """A transport-neutral Streaming command."""

    operation_id: str
    operation_type: StreamingOperationType
    payload: Mapping[str, object]
    idempotency_key: StreamingIdempotencyKey | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class StreamingOperationResult:
    """Acceptance or completion result without exception-only failures."""

    operation_id: str
    accepted: bool
    status: StreamingStatus
    error: StreamingError | None = None
    payload: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
