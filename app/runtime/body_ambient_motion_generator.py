from __future__ import annotations

import math
import random
from dataclasses import dataclass

from app.domain.body_motion_state import BodyInnerMotionState


@dataclass(frozen=True, slots=True)
class BodyAmbientMotionSample:
    scan_x: float
    scan_y: float
    posture_noise: float
    head_noise: float


class BodyAmbientMotionGenerator:
    """相関した視線探索・姿勢揺らぎ・頭部微動だけを生成する。"""

    def __init__(self, *, seed: int | None = None) -> None:
        self._random = random.Random(seed)
        self._scan_x = 0.0
        self._scan_y = 0.0
        self._scan_vx = 0.0
        self._scan_vy = 0.0
        self._posture_noise = 0.0
        self._posture_velocity = 0.0
        self._head_noise = 0.0
        self._head_velocity = 0.0

    def step(
        self,
        *,
        dt_seconds: float,
        state: BodyInnerMotionState,
    ) -> BodyAmbientMotionSample:
        if not isinstance(state, BodyInnerMotionState):
            raise TypeError("state must be BodyInnerMotionState")
        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        root_dt = math.sqrt(dt)

        scan_sigma = 0.08 + state.curiosity * 0.34 + state.tension * 0.16
        scan_reversion = 0.65 + state.engagement * 0.55
        self._scan_vx += (-scan_reversion * self._scan_x - 1.7 * self._scan_vx) * dt
        self._scan_vy += (-scan_reversion * self._scan_y - 1.8 * self._scan_vy) * dt
        self._scan_vx += self._random.gauss(0.0, scan_sigma) * root_dt
        self._scan_vy += self._random.gauss(0.0, scan_sigma * 0.72) * root_dt
        self._scan_x = self._clamp(self._scan_x + self._scan_vx * dt, -0.82, 0.82)
        self._scan_y = self._clamp(self._scan_y + self._scan_vy * dt, -0.58, 0.58)

        posture_sigma = 0.025 + state.movement_energy * 0.08
        self._posture_velocity += (
            -0.42 * self._posture_noise - 0.95 * self._posture_velocity
        ) * dt
        self._posture_velocity += self._random.gauss(0.0, posture_sigma) * root_dt
        self._posture_noise = self._clamp(
            self._posture_noise + self._posture_velocity * dt,
            -0.24,
            0.24,
        )

        head_sigma = 0.02 + state.arousal * 0.055 + state.curiosity * 0.035
        self._head_velocity += (
            -0.58 * self._head_noise - 1.1 * self._head_velocity
        ) * dt
        self._head_velocity += self._random.gauss(0.0, head_sigma) * root_dt
        self._head_noise = self._clamp(
            self._head_noise + self._head_velocity * dt,
            -0.18,
            0.18,
        )

        return BodyAmbientMotionSample(
            scan_x=self._scan_x,
            scan_y=self._scan_y,
            posture_noise=self._posture_noise,
            head_noise=self._head_noise,
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
