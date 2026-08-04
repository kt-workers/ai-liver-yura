from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AvatarGazeIntent:
    """描画方式に依存しない高レベル視線Intent。"""

    target: str
    behavior: str = "maintain"
    intensity: float = 1.0

    def __post_init__(self) -> None:
        normalized_target = self.target.strip()
        normalized_behavior = self.behavior.strip()
        if not normalized_target:
            raise ValueError("target must not be empty")
        if not normalized_behavior:
            raise ValueError("behavior must not be empty")
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError("intensity must be between 0.0 and 1.0")
        object.__setattr__(self, "target", normalized_target)
        object.__setattr__(self, "behavior", normalized_behavior)


class AvatarOutputPort(Protocol):
    """Live2D等の実装に依存しないアバター出力契約。"""

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
