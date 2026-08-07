from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class BodyInstruction:
    """入力意味解析が確定した、モデル非依存の身体指示。

    Pose軸、角度、モーション名、再生時刻は含めない。Body Runtimeが
    effector / direction / side / magnitudeを現在状態へ重ねる一時制約へ変換する。
    """

    effector: str
    direction: str
    side: str | None = None
    magnitude: float = 1.0

    def __post_init__(self) -> None:
        effector = self.effector.strip().lower()
        direction = self.direction.strip().lower()
        side = self.side.strip().lower() if isinstance(self.side, str) else None
        if not effector or len(effector) > 64:
            raise ValueError("effector must be a non-empty string up to 64 characters")
        if not direction or len(direction) > 64:
            raise ValueError("direction must be a non-empty string up to 64 characters")
        if side is not None and (not side or len(side) > 32):
            raise ValueError("side must be null or a non-empty string up to 32 characters")
        if isinstance(self.magnitude, bool) or not isinstance(
            self.magnitude, (int, float)
        ):
            raise TypeError("magnitude must be a number")
        magnitude = float(self.magnitude)
        if not 0.0 <= magnitude <= 1.0:
            raise ValueError("magnitude must be between 0.0 and 1.0")
        object.__setattr__(self, "effector", effector)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "magnitude", magnitude)

    def as_context(self) -> dict[str, object]:
        return {
            "effector": self.effector,
            "direction": self.direction,
            "side": self.side,
            "magnitude": self.magnitude,
        }

    @classmethod
    def from_context(cls, value: object) -> BodyInstruction | None:
        if not isinstance(value, dict):
            return None
        effector = value.get("effector")
        direction = value.get("direction")
        side = value.get("side")
        magnitude = value.get("magnitude", 1.0)
        if not isinstance(effector, str) or not isinstance(direction, str):
            return None
        if side is not None and not isinstance(side, str):
            return None
        try:
            return cls(
                effector=effector,
                direction=direction,
                side=side,
                magnitude=magnitude,  # type: ignore[arg-type]
            )
        except (TypeError, ValueError):
            return None


class BodyConstraintExecutionStatus(str, Enum):
    APPLIED = "applied"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class BodyConstraintExecutionResult:
    """Speechとは独立した、一時Body制約の実行結果。"""

    status: BodyConstraintExecutionStatus
    constraint_id: str | None
    reason: str
    target_axes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            raise ValueError("reason must not be empty")
        if self.constraint_id is not None:
            constraint_id = self.constraint_id.strip()
            if not constraint_id:
                raise ValueError("constraint_id must not be blank")
            object.__setattr__(self, "constraint_id", constraint_id[:128])
        object.__setattr__(self, "reason", reason[:240])
        object.__setattr__(
            self,
            "target_axes",
            tuple(str(axis).strip() for axis in self.target_axes if str(axis).strip()),
        )

    @property
    def applied(self) -> bool:
        return self.status is BodyConstraintExecutionStatus.APPLIED

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "constraint_id": self.constraint_id,
            "reason": self.reason,
            "target_axes": list(self.target_axes),
        }


__all__ = [
    "BodyConstraintExecutionResult",
    "BodyConstraintExecutionStatus",
    "BodyInstruction",
]
