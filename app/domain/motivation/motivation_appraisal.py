from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.desires import DesireType


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True, slots=True)
class RankedDesire:
    """Motivation Appraisalで順位付けされた欲望。"""

    desire_type: DesireType
    rank: int
    effective_level: float
    expressed_level: float

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rankは1以上にしてください。")
        object.__setattr__(self, "effective_level", _clamp_01(self.effective_level))
        object.__setattr__(self, "expressed_level", _clamp_01(self.expressed_level))

    def as_context(self) -> dict[str, object]:
        return {
            "desire_type": self.desire_type.value,
            "rank": self.rank,
            "effective_level": self.effective_level,
            "expressed_level": self.expressed_level,
        }


@dataclass(frozen=True, slots=True)
class DesireConflict:
    """同時に強くなり、方針が競合し得る欲望の組。"""

    left: DesireType
    right: DesireType
    intensity: float
    reason: str

    def __post_init__(self) -> None:
        if self.left == self.right:
            raise ValueError("同じ欲望同士は競合にできません。")
        if not self.reason.strip():
            raise ValueError("reasonは空にできません。")
        object.__setattr__(self, "intensity", _clamp_01(self.intensity))

    def as_context(self) -> dict[str, object]:
        return {
            "left": self.left.value,
            "right": self.right.value,
            "intensity": self.intensity,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class MotivationAppraisal:
    """DesireとRelationshipから導出する読み取り専用の動機評価。"""

    ranked_desires: tuple[RankedDesire, ...] = ()
    conflicts: tuple[DesireConflict, ...] = ()
    expression_strength: float = 0.5
    recommended_activity_types: tuple[str, ...] = ()
    recommended_conversation_strategies: tuple[str, ...] = ()
    moral_evaluation_available: bool = False
    suppressed_activity_types: tuple[str, ...] = ()
    suppression_reasons: tuple[str, ...] = field(
        default_factory=lambda: ("moral_profile_not_available",)
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "expression_strength",
            _clamp_01(self.expression_strength),
        )
        if len({item.rank for item in self.ranked_desires}) != len(
            self.ranked_desires
        ):
            raise ValueError("ranked_desiresのrankは重複できません。")
        if self.moral_evaluation_available is False and self.suppressed_activity_types:
            raise ValueError(
                "Moral評価が利用不可の場合はActivityを抑制できません。"
            )

    @property
    def primary_desire(self) -> DesireType | None:
        if not self.ranked_desires:
            return None
        return min(self.ranked_desires, key=lambda item: item.rank).desire_type

    def as_context(self) -> dict[str, object]:
        return {
            "primary_desire": (
                self.primary_desire.value if self.primary_desire is not None else None
            ),
            "ranked_desires": [
                desire.as_context() for desire in self.ranked_desires
            ],
            "conflicts": [conflict.as_context() for conflict in self.conflicts],
            "expression_strength": self.expression_strength,
            "recommended_activity_types": list(self.recommended_activity_types),
            "recommended_conversation_strategies": list(
                self.recommended_conversation_strategies
            ),
            "moral_evaluation_available": self.moral_evaluation_available,
            "suppressed_activity_types": list(self.suppressed_activity_types),
            "suppression_reasons": list(self.suppression_reasons),
        }
