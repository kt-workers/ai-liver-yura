"""Gateway protocol for a future Game Subsystem adapter."""

from collections.abc import Sequence
from typing import Protocol

from app.integrations.games.contracts import (
    GameCommandResult,
    GameSubsystemCommand,
    GameSubsystemSnapshot,
    GameSubsystemStatus,
)
from app.integrations.games.events import GameSubsystemEvent


class GameSubsystemGateway(Protocol):
    """Asynchronous boundary implemented by Null and transport adapters."""

    async def get_status(self) -> GameSubsystemStatus:
        """Return the current subsystem status."""
        ...

    async def get_snapshot(self) -> GameSubsystemSnapshot:
        """Return the current transport-neutral snapshot."""
        ...

    async def send_command(self, command: GameSubsystemCommand) -> GameCommandResult:
        """Submit a command without exposing transport details."""
        ...

    async def poll_events(self) -> Sequence[GameSubsystemEvent]:
        """Return events currently available to the caller."""
        ...
