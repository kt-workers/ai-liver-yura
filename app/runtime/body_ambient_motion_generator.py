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
    """相関した探索微動と、別時間スケールの低周波姿勢移動を生成する。"""

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
        self._posture_sway_phase = 0.0
        self._head_sway_phase = math.pi * 0.35

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

        posture_frequency_hz = (
            0.035 + state.movement_energy * 0.018 + state.arousal * 0.008
        )
        head_frequency_hz = (
            0.047 + state.curiosity * 0.014 + state.engagement * 0.009
        )
        self._posture_sway_phase = (
            self._posture_sway_phase + math.tau * posture_frequency_hz * dt
        ) % math.tau
        self._head_sway_phase = (
            self._head_sway_phase + math.tau * head_frequency_hz * dt
        ) % math.tau

        posture_sway_amplitude = (
            0.035 + state.movement_energy * 0.07 + state.engagement * 0.025
        )
        head_sway_amplitude = (
            0.02 + state.arousal * 0.035 + state.curiosity * 0.025
        )
        posture_motion = self._clamp(
            self._posture_noise
            + math.sin(self._posture_sway_phase) * posture_sway_amplitude,
            -0.18,
            0.18,
        )
        head_motion = self._clamp(
            self._head_noise
            + math.sin(self._head_sway_phase) * head_sway_amplitude,
            -0.14,
            0.14,
        )

        return BodyAmbientMotionSample(
            scan_x=self._scan_x,
            scan_y=self._scan_y,
            posture_noise=posture_motion,
            head_noise=head_motion,
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
