from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.body_motion_state import BodyInnerMotionState


@dataclass(frozen=True, slots=True)
class BodyBreathingSample:
    body_height: float
    torso_pitch: float


class BodyBreathingOscillator:
    """内的運動Snapshotから連続した呼吸成分だけを生成する。"""

    def __init__(self, *, initial_phase: float = 0.0) -> None:
        self._phase = float(initial_phase) % math.tau

    @property
    def phase(self) -> float:
        return self._phase

    def step(
        self,
        *,
        dt_seconds: float,
        state: BodyInnerMotionState,
    ) -> BodyBreathingSample:
        if not isinstance(state, BodyInnerMotionState):
            raise TypeError("state must be BodyInnerMotionState")
        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        frequency_hz = 0.13 + state.arousal * 0.09 + state.tension * 0.055
        self._phase = (self._phase + math.tau * frequency_hz * dt) % math.tau
        wave = math.sin(self._phase)
        amplitude = (
            0.025
            + state.movement_energy * 0.035
            + state.arousal * 0.018
        )
        return BodyBreathingSample(
            body_height=wave * amplitude,
            torso_pitch=-wave * amplitude * 0.34,
        )
