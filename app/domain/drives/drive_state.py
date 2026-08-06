from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DriveState:
    """行動内容ではなく、現在の活性・関与・疲労を表す派生状態。"""

    curiosity: float = 0.5
    engagement: float = 0.5
    boredom: float = 0.0
    energy: float = 0.7

    def __post_init__(self) -> None:
        object.__setattr__(self, "curiosity", self._clamp_01(self.curiosity))
        object.__setattr__(self, "engagement", self._clamp_01(self.engagement))
        object.__setattr__(self, "boredom", self._clamp_01(self.boredom))
        object.__setattr__(self, "energy", self._clamp_01(self.energy))

    def should_start_autonomous_talk(self) -> bool:
        """旧自律発話判定との互換API。Phase 4でInteraction Intentionへ移行する。"""

        return (
            self.curiosity >= 0.7 or self.engagement >= 0.75 or self.boredom >= 0.8
        ) and self.energy >= 0.3

    def strongest_drive_name(self) -> str:
        """現在もっとも強い活性指標名を返す。"""

        drives = {
            "curiosity": self.curiosity,
            "engagement": self.engagement,
            "boredom": self.boredom,
            "energy": self.energy,
        }
        return max(drives, key=lambda drive_name: drives[drive_name])

    @staticmethod
    def _clamp_01(value: float) -> float:
        return max(0.0, min(1.0, value))
