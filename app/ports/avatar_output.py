from __future__ import annotations

from dataclasses import dataclass
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
