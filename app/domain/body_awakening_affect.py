from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_value_validation import bounded_number


@dataclass(frozen=True, slots=True)
class BodyAwakeningAffect:
    """覚醒AppraisalをBodyへ渡す、Pose・Motion非依存の連続表現傾向。"""

    activation: float = 0.0
    drowsiness: float = 0.0
    orientation: float = 0.0
    security: float = 0.0
    exploration: float = 0.0
    social: float = 0.0
    readiness: float = 0.0
    salience: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "activation",
            "drowsiness",
            "orientation",
            "security",
            "exploration",
            "social",
            "readiness",
            "salience",
        ):
            object.__setattr__(
                self,
                name,
                bounded_number(getattr(self, name), name, 0.0, 1.0),
            )

    @property
    def active(self) -> bool:
        return self.salience > 0.0

    def as_payload(self) -> dict[str, float]:
        return {
            "activation": self.activation,
            "drowsiness": self.drowsiness,
            "orientation": self.orientation,
            "security": self.security,
            "exploration": self.exploration,
            "social": self.social,
            "readiness": self.readiness,
            "salience": self.salience,
        }


__all__ = ["BodyAwakeningAffect"]
