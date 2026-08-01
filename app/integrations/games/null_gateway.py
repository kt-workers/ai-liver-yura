"""No-I/O Game Subsystem gateway used while the subsystem is absent."""

from app.integrations.games.contracts import (
    GameCommandResult,
    GameSubsystemCommand,
    GameSubsystemSnapshot,
    GameSubsystemStatus,
)
from app.integrations.games.events import GameSubsystemEvent

GAME_SUBSYSTEM_NOT_CONNECTED = "game_subsystem_not_connected"


class NullGameSubsystemGateway:
    """Stable disconnected behavior without I/O or mutable state."""

    async def get_status(self) -> GameSubsystemStatus:
        return GameSubsystemStatus.DISCONNECTED

    async def get_snapshot(self) -> GameSubsystemSnapshot:
        return GameSubsystemSnapshot(
            status=GameSubsystemStatus.DISCONNECTED,
            active_session_id=None,
            message=GAME_SUBSYSTEM_NOT_CONNECTED,
        )

    async def send_command(self, command: GameSubsystemCommand) -> GameCommandResult:
        del command
        return GameCommandResult(
            accepted=False,
            status=GameSubsystemStatus.DISCONNECTED,
            reason=GAME_SUBSYSTEM_NOT_CONNECTED,
        )

    async def poll_events(self) -> tuple[GameSubsystemEvent, ...]:
        return ()
