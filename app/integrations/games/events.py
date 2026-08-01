"""Event contracts emitted by a Game Subsystem."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class GameEventType(str, Enum):
    """Events understood at the subsystem boundary."""

    STATUS_CHANGED = "status_changed"
    SESSION_STARTED = "session_started"
    OUTPUT_AVAILABLE = "output_available"
    SESSION_ENDED = "session_ended"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class GameSubsystemEvent:
    """A transport-neutral event received from the Game Subsystem."""

    event_id: str
    event_type: GameEventType
    payload: Mapping[str, object]
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
