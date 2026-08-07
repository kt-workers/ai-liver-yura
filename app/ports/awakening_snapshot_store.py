from __future__ import annotations

from typing import Protocol

from app.domain.awakening import AwakeningSnapshot, AwakeningSnapshotLoadResult


class AwakeningSnapshotStore(Protocol):
    """起動評価に必要な最小Snapshotだけを保存するPort。"""

    def load(self) -> AwakeningSnapshotLoadResult: ...

    def save(self, snapshot: AwakeningSnapshot) -> None: ...


__all__ = ["AwakeningSnapshotStore"]
