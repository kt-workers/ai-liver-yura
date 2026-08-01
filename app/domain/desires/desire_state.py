from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class DesireType(str, Enum):
    """キャラクターが現在満たしたい欲望の種類。"""

    CONNECTION = "connection"
    CURIOSITY = "curiosity"
    EXPRESSION = "expression"
    RECOGNITION = "recognition"
    AUTONOMY = "autonomy"
    SECURITY = "security"
    ACHIEVEMENT = "achievement"


@dataclass(frozen=True, slots=True)
class DesireValue:
    """1種類の欲望について、現在値と充足状態を保持する。"""

    level: float
    baseline: float
    sensitivity: float = 1.0
    satisfaction: float = 0.0
    frustration: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "level",
            "baseline",
            "sensitivity",
            "satisfaction",
            "frustration",
        ):
            object.__setattr__(self, name, self._clamp_01(getattr(self, name)))

    @property
    def effective_level(self) -> float:
        """最近の充足と不満を反映した、観測用の実効欲望値を返す。"""

        return self._clamp_01(self.level + self.frustration - self.satisfaction)

    def adjusted(
        self,
        *,
        level_delta: float = 0.0,
        satisfaction_delta: float = 0.0,
        frustration_delta: float = 0.0,
    ) -> DesireValue:
        """感度を反映した増減を適用し、新しい値を返す。"""

        return replace(
            self,
            level=self.level + level_delta * self.sensitivity,
            satisfaction=(
                self.satisfaction + satisfaction_delta * self.sensitivity
            ),
            frustration=self.frustration + frustration_delta * self.sensitivity,
        )

    @staticmethod
    def _clamp_01(value: float) -> float:
        return max(0.0, min(1.0, value))


def _desire_value(baseline: float) -> DesireValue:
    return DesireValue(level=baseline, baseline=baseline)


@dataclass(frozen=True, slots=True)
class DesireState:
    """7種類の欲望を、EmotionやDriveとは別に保持する観測用状態。"""

    connection: DesireValue = field(default_factory=lambda: _desire_value(0.45))
    curiosity: DesireValue = field(default_factory=lambda: _desire_value(0.50))
    expression: DesireValue = field(default_factory=lambda: _desire_value(0.40))
    recognition: DesireValue = field(default_factory=lambda: _desire_value(0.30))
    autonomy: DesireValue = field(default_factory=lambda: _desire_value(0.40))
    security: DesireValue = field(default_factory=lambda: _desire_value(0.35))
    achievement: DesireValue = field(default_factory=lambda: _desire_value(0.35))

    def get(self, desire_type: DesireType) -> DesireValue:
        return getattr(self, desire_type.value)

    def with_value(
        self,
        desire_type: DesireType,
        value: DesireValue,
    ) -> DesireState:
        return replace(self, **{desire_type.value: value})

    def effective_values(self) -> dict[str, float]:
        return {
            desire_type.value: self.get(desire_type).effective_level
            for desire_type in DesireType
        }

    def as_dict(self) -> dict[str, dict[str, float]]:
        return {
            desire_type.value: {
                "level": value.level,
                "baseline": value.baseline,
                "sensitivity": value.sensitivity,
                "satisfaction": value.satisfaction,
                "frustration": value.frustration,
                "effective_level": value.effective_level,
            }
            for desire_type in DesireType
            for value in (self.get(desire_type),)
        }

    def strongest_desire_name(self) -> str:
        values = self.effective_values()
        return max(values, key=lambda desire_name: values[desire_name])
