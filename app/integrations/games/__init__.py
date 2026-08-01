"""Transport-neutral contracts for a future Game Subsystem."""

from app.integrations.games.contracts import (
    GameCommandResult,
    GameCommandType,
    GameSubsystemCommand,
    GameSubsystemSnapshot,
    GameSubsystemStatus,
)
from app.integrations.games.events import GameEventType, GameSubsystemEvent
from app.integrations.games.gateway import GameSubsystemGateway
from app.integrations.games.null_gateway import (
    GAME_SUBSYSTEM_NOT_CONNECTED,
    NullGameSubsystemGateway,
)

__all__ = [
    "GAME_SUBSYSTEM_NOT_CONNECTED",
    "GameCommandResult",
    "GameCommandType",
    "GameEventType",
    "GameSubsystemCommand",
    "GameSubsystemEvent",
    "GameSubsystemGateway",
    "GameSubsystemSnapshot",
    "GameSubsystemStatus",
    "NullGameSubsystemGateway",
]
