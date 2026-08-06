from __future__ import annotations

import math
import random
from dataclasses import dataclass

from app.domain.body_motion_state import BodyInnerMotionState


@dataclass(frozen=True, slots=True)
class BodyBlinkSample:
    eye_open: float
    blinking: bool


class BodyBlinkScheduler:
    """瞬きの発生間隔と開閉進行だけを管理する。"""

    def __init__(self, *, seed: int | None = None) -> None:
        self._random = random.Random(seed)
        self._elapsed = 0.0
        self._progress: float | None = None
        self._forced = False

    @property
    def blinking(self) -> bool:
        return self._progress is not None

    def request_blink(self) -> None:
        self._forced = True

    def step(
        self,
        *,
        dt_seconds: float,
        state: BodyInnerMotionState,
    ) -> BodyBlinkSample:
        if not isinstance(state, BodyInnerMotionState):
            raise TypeError("state must be BodyInnerMotionState")
        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        self._elapsed += dt

        if self._progress is None:
            minimum_interval = 1.25 + (1.0 - state.tension) * 0.75
            hazard = 0.10 + state.tension * 0.21 + state.arousal * 0.11
            should_start = self._forced or (
                self._elapsed >= minimum_interval
                and self._random.random() < hazard * dt
            )
            if should_start:
                self._forced = False
                self._progress = 0.0
                self._elapsed = 0.0
            else:
                return BodyBlinkSample(eye_open=1.0, blinking=False)

        duration = max(0.16, 0.24 - state.tension * 0.055)
        self._progress += dt / duration
        progress = min(1.0, self._progress)
        eye_open = 1.0 - math.sin(math.pi * progress)
        if self._progress >= 1.0:
            self._progress = None
            eye_open = 1.0
        return BodyBlinkSample(
            eye_open=max(0.0, min(1.0, eye_open)),
            blinking=self._progress is not None,
        )
