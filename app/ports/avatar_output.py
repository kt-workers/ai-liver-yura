from __future__ import annotations

from threading import RLock
from typing import Protocol

from app.domain.avatar_performance import AvatarGazeIntent, AvatarPerformancePlan

__all__ = [
    "AvatarGazeIntent",
    "AvatarOutputPort",
    "AvatarPerformancePlan",
    "bind_avatar_output",
    "get_bound_avatar_output",
]


class AvatarOutputPort(Protocol):
    """Live2D等の実装に依存しないアバター出力契約。"""

    async def submit_performance(
        self,
        performance: AvatarPerformancePlan,
    ) -> None:
        """時間軸付きの高レベル演技計画をアバターへ送信する。"""
        ...

    async def set_expression(self, expression: str) -> None:
        """高レベルな表情名をアバターへ反映する。"""
        ...

    async def play_gesture(self, gesture: str) -> None:
        """高レベルなジェスチャー名をアバターへ反映する。"""
        ...

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        """高レベルな視線Intentをアバターへ反映する。"""
        ...


_binding_lock = RLock()
_bound_avatar_output: AvatarOutputPort | None = None


def bind_avatar_output(output: AvatarOutputPort | None) -> None:
    """Composition Rootが初期化済みAvatar Outputをプロセスへ束縛する。

    Web MVP期間の移行用境界であり、正式なRuntime依存定義ではConstructor
    Injectionへ置き換える。Runtime再構成時にNoneを渡すと以前の束縛を解除する。
    """

    global _bound_avatar_output
    with _binding_lock:
        _bound_avatar_output = output


def get_bound_avatar_output() -> AvatarOutputPort | None:
    """現在Composition Rootが束縛しているAvatar Outputを返す。"""

    with _binding_lock:
        return _bound_avatar_output
