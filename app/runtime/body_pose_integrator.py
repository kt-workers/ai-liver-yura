from __future__ import annotations

from dataclasses import dataclass, fields

from app.domain.body_auxiliary_projection import (
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.domain.body_pose_dynamics import BodyPoseDynamicsState


@dataclass(frozen=True, slots=True)
class BodyAxisDynamicsProfile:
    stiffness: float
    damping: float
    max_speed: float


_FAST = BodyAxisDynamicsProfile(52.0, 14.0, 6.0)
_HEAD = BodyAxisDynamicsProfile(28.0, 10.0, 4.0)
_TORSO = BodyAxisDynamicsProfile(16.0, 8.0, 2.5)
_ARM = BodyAxisDynamicsProfile(12.0, 7.0, 2.0)
_HEIGHT = BodyAxisDynamicsProfile(18.0, 8.0, 2.5)

_PROFILES: dict[str, BodyAxisDynamicsProfile] = {
    "gaze_x": _FAST,
    "gaze_y": _FAST,
    "eye_left_open": _FAST,
    "eye_right_open": _FAST,
    "mouth_open": _FAST,
    "mouth_form": _FAST,
    "head_yaw": _HEAD,
    "head_pitch": _HEAD,
    "head_roll": _HEAD,
    "torso_yaw": _TORSO,
    "torso_pitch": _TORSO,
    "torso_roll": _TORSO,
    "body_height": _HEIGHT,
    "left_arm_raise": _ARM,
    "right_arm_raise": _ARM,
    "left_arm_in": _ARM,
    "right_arm_in": _ARM,
}

_UNIT_FIELDS = {
    "eye_left_open",
    "eye_right_open",
    "mouth_open",
    "left_arm_raise",
    "right_arm_raise",
}


class BodyPoseIntegrator:
    """現在Poseと速度を保持せず、1Stepのばね・減衰積分だけを行う。"""

    def step(
        self,
        *,
        state: BodyPoseDynamicsState,
        target: BodyTrackingPose,
        dt_seconds: float,
    ) -> BodyPoseDynamicsState:
        if not isinstance(state, BodyPoseDynamicsState):
            raise TypeError("state must be BodyPoseDynamicsState")
        if not isinstance(target, BodyTrackingPose):
            raise TypeError("target must be BodyTrackingPose")
        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))

        pose_values: dict[str, float] = {}
        velocity_values: dict[str, float] = {}
        for value_field in fields(BodyTrackingPose):
            name = value_field.name
            profile = _PROFILES[name]
            current = getattr(state.pose, name)
            velocity = getattr(state.velocity, name)
            desired = getattr(target, name)
            acceleration = profile.stiffness * (desired - current)
            acceleration -= profile.damping * velocity
            next_velocity = self._clamp(
                velocity + acceleration * dt,
                -profile.max_speed,
                profile.max_speed,
            )
            next_pose = current + next_velocity * dt
            minimum, maximum = (0.0, 1.0) if name in _UNIT_FIELDS else (-1.0, 1.0)
            pose_values[name] = self._clamp(next_pose, minimum, maximum)
            velocity_values[name] = next_velocity

        return BodyPoseDynamicsState(
            pose=BodyTrackingPose(**pose_values),
            velocity=BodyTrackingVelocity(**velocity_values),
        )

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
