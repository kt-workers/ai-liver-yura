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

        scan_sigma = 0.035 + state.curiosity * 0.14 + state.tension * 0.06
        scan_reversion = 0.78 + state.engagement * 0.62
        self._scan_vx += (-scan_reversion * self._scan_x - 2.15 * self._scan_vx) * dt
        self._scan_vy += (-scan_reversion * self._scan_y - 2.25 * self._scan_vy) * dt
        self._scan_vx += self._random.gauss(0.0, scan_sigma) * root_dt
        self._scan_vy += self._random.gauss(0.0, scan_sigma * 0.68) * root_dt
        self._scan_vx = self._clamp(self._scan_vx, -0.38, 0.38)
        self._scan_vy = self._clamp(self._scan_vy, -0.32, 0.32)
        self._scan_x = self._clamp(self._scan_x + self._scan_vx * dt, -0.72, 0.72)
        self._scan_y = self._clamp(self._scan_y + self._scan_vy * dt, -0.48, 0.48)

        posture_sigma = 0.006 + state.movement_energy * 0.022
        self._posture_velocity += (
            -0.68 * self._posture_noise - 1.55 * self._posture_velocity
        ) * dt
        self._posture_velocity += self._random.gauss(0.0, posture_sigma) * root_dt
        self._posture_velocity = self._clamp(self._posture_velocity, -0.065, 0.065)
        self._posture_noise = self._clamp(
            self._posture_noise + self._posture_velocity * dt,
            -0.12,
            0.12,
        )

        head_sigma = 0.005 + state.arousal * 0.016 + state.curiosity * 0.012
        self._head_velocity += (
            -0.82 * self._head_noise - 1.72 * self._head_velocity
        ) * dt
        self._head_velocity += self._random.gauss(0.0, head_sigma) * root_dt
        self._head_velocity = self._clamp(self._head_velocity, -0.052, 0.052)
        self._head_noise = self._clamp(
            self._head_noise + self._head_velocity * dt,
            -0.09,
            0.09,
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
