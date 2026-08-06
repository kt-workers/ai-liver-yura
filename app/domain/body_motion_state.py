from __future__ import annotations

from dataclasses import dataclass, fields

from app.domain.body_value_validation import bounded_number


@dataclass(frozen=True, slots=True)
class BodyInnerMotionState:
    """Body Pose生成時点のモデル非依存な内的運動Snapshot。

    心理状態の決定や更新は行わず、上流で確定した値を0〜1で保持する。
    """

    arousal: float = 0.35
    tension: float = 0.2
    curiosity: float = 0.4
    confidence: float = 0.5
    engagement: float = 0.5
    avoidance: float = 0.0
    movement_energy: float = 0.35

    def __post_init__(self) -> None:
        for value_field in fields(self):
            object.__setattr__(
                self,
                value_field.name,
                bounded_number(
                    getattr(self, value_field.name),
                    value_field.name,
                    0.0,
                    1.0,
                ),
            )

    def as_payload(self) -> dict[str, float]:
        return {
            value_field.name: getattr(self, value_field.name)
            for value_field in fields(self)
        }
