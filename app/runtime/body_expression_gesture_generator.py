from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.body_expression import EmbodiedExpressionIntent


@dataclass(frozen=True, slots=True)
class BodyExpressionGestureSample:
    head_yaw: float = 0.0
    head_pitch: float = 0.0
    head_roll: float = 0.0


class BodyExpressionGestureGenerator:
    """agreement等の意味軸から小さな頭部リズムだけを生成する。"""

    def __init__(self) -> None:
        self._phase = 0.0

    def step(
        self,
        *,
        dt_seconds: float,
        expression: EmbodiedExpressionIntent | None,
    ) -> BodyExpressionGestureSample:
        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        if expression is None or abs(expression.agreement) < 0.08:
            self._phase = 0.0
            return BodyExpressionGestureSample()

        frequency = 1.4 + expression.arousal * 0.8
        if expression.agreement < 0.0:
            frequency += 0.4
        self._phase = (self._phase + math.tau * frequency * dt) % math.tau
        wave = math.sin(self._phase)
        strength = expression.intensity * abs(expression.agreement)
        if expression.agreement > 0.0:
            return BodyExpressionGestureSample(
                head_pitch=wave * strength * 0.24,
            )
        return BodyExpressionGestureSample(
            head_yaw=wave * strength * 0.34,
            head_roll=-wave * strength * 0.06,
        )
