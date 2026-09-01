from __future__ import annotations

from datetime import datetime
from threading import Lock

from .contracts import (
    AvatarProjectionCommand,
    AvatarRendererResult,
    AvatarRendererStatus,
)


class StickAvatarRenderer:
    """検証用Stick renderer。projection commandを保持するだけで意味判断しない。"""

    def __init__(self, *, available: bool = True) -> None:
        if type(available) is not bool:
            raise ValueError("availableはboolでなければなりません")
        self._available = available
        self._latest: AvatarProjectionCommand | None = None
        self._lock = Lock()

    @property
    def available(self) -> bool:
        with self._lock:
            return self._available

    @property
    def latest_command(self) -> AvatarProjectionCommand | None:
        with self._lock:
            return self._latest

    def set_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise ValueError("availableはboolでなければなりません")
        with self._lock:
            self._available = available

    def present(
        self,
        command: AvatarProjectionCommand,
        *,
        started_at: datetime,
    ) -> AvatarRendererResult:
        if not isinstance(command, AvatarProjectionCommand):
            raise ValueError("commandが不正です")
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("started_atはtimezone-awareでなければなりません")
        with self._lock:
            if not self._available:
                return AvatarRendererResult(
                    AvatarRendererStatus.UNAVAILABLE,
                    started_at,
                    ("stick_renderer_unavailable",),
                )
            self._latest = command
        return AvatarRendererResult(AvatarRendererStatus.APPLIED, started_at)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            command = self._latest
            return {
                "available": self._available,
                "latest_command": None if command is None else command.to_dict(),
            }
