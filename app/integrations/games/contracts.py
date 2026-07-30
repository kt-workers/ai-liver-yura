"""Command, result, snapshot, and status contracts for a Game Subsystem."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class GameSubsystemStatus(str, Enum):
    """Transport-neutral availability and activity status."""

    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"


class GameCommandType(str, Enum):
    """Commands understood at the subsystem boundary."""

    START = "start"
    INPUT = "input"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    RESET = "reset"


@dataclass(frozen=True, slots=True)
class GameSubsystemCommand:
    """A transport-neutral request sent to the Game Subsystem."""

    command_id: str
    command_type: GameCommandType
    payload: Mapping[str, object]
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class GameCommandResult:
    """The boundary-level result of accepting a command."""

    accepted: bool
    status: GameSubsystemStatus
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class GameSubsystemSnapshot:
    """A minimal point-in-time view of the subsystem."""

    status: GameSubsystemStatus
    active_session_id: str | None
    message: str | None = None
