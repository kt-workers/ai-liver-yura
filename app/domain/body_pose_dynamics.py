from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum

from app.domain.body_auxiliary_projection import (
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.domain.body_value_validation import (
    bounded_number,
    non_negative_integer,
    normalized_identifier,
)


class BodyPoseAxis(str, Enum):
    HEAD_YAW = "head_yaw"
    HEAD_PITCH = "head_pitch"
    HEAD_ROLL = "head_roll"
    GAZE_X = "gaze_x"
    GAZE_Y = "gaze_y"
    EYE_LEFT_OPEN = "eye_left_open"
    EYE_RIGHT_OPEN = "eye_right_open"
    MOUTH_OPEN = "mouth_open"
    MOUTH_FORM = "mouth_form"
    TORSO_YAW = "torso_yaw"
    TORSO_PITCH = "torso_pitch"
    TORSO_ROLL = "torso_roll"
    BODY_HEIGHT = "body_height"
    LEFT_ARM_RAISE = "left_arm_raise"
    RIGHT_ARM_RAISE = "right_arm_raise"
    LEFT_ARM_IN = "left_arm_in"
    RIGHT_ARM_IN = "right_arm_in"


_UNIT_AXES = {
    BodyPoseAxis.EYE_LEFT_OPEN,
    BodyPoseAxis.EYE_RIGHT_OPEN,
    BodyPoseAxis.MOUTH_OPEN,
    BodyPoseAxis.LEFT_ARM_RAISE,
    BodyPoseAxis.RIGHT_ARM_RAISE,
}


@dataclass(frozen=True, slots=True)
class BodyPoseDynamicsState:
    """連続Pose積分器が保持する現在姿勢と速度。"""

    pose: BodyTrackingPose = field(default_factory=BodyTrackingPose)
    velocity: BodyTrackingVelocity = field(default_factory=BodyTrackingVelocity)

    def __post_init__(self) -> None:
        if not isinstance(self.pose, BodyTrackingPose):
            raise TypeError("pose must be BodyTrackingPose")
        if not isinstance(self.velocity, BodyTrackingVelocity):
            raise TypeError("velocity must be BodyTrackingVelocity")


@dataclass(frozen=True, slots=True)
class BodyPoseConstraintTarget:
    """一時外部制約が寄せる単一Pose軸の目標。"""

    axis: BodyPoseAxis
    value: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        axis = self.axis
        if isinstance(axis, str):
            axis = BodyPoseAxis(axis)
        if not isinstance(axis, BodyPoseAxis):
            raise TypeError("axis must be BodyPoseAxis")
        object.__setattr__(self, "axis", axis)
        minimum, maximum = (0.0, 1.0) if axis in _UNIT_AXES else (-1.0, 1.0)
        object.__setattr__(
            self,
            "value",
            bounded_number(self.value, "value", minimum, maximum),
        )
        object.__setattr__(
            self,
            "weight",
            bounded_number(self.weight, "weight", 0.0, 1.0),
        )


@dataclass(frozen=True, slots=True)
class BodyExternalConstraint:
    """感情基礎Poseへ短時間だけ重ねる、意味解決済みの外部制約。

    Motion名、Character発話、実行成功の主張は含まない。
    """

    constraint_id: str
    targets: tuple[BodyPoseConstraintTarget, ...]
    duration_ms: int
    attack_ratio: float = 0.18
    release_ratio: float = 0.24

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint_id",
            normalized_identifier(
                self.constraint_id,
                "constraint_id",
                maximum_length=128,
            ),
        )
        targets = tuple(self.targets)
        if not targets:
            raise ValueError("targets must not be empty")
        if len(targets) > len(fields(BodyTrackingPose)):
            raise ValueError("too many constraint targets")
        if not all(isinstance(target, BodyPoseConstraintTarget) for target in targets):
            raise TypeError("targets must contain BodyPoseConstraintTarget values")
        axes = [target.axis for target in targets]
        if len(axes) != len(set(axes)):
            raise ValueError("constraint axes must be unique")
        object.__setattr__(self, "targets", targets)
        duration = non_negative_integer(self.duration_ms, "duration_ms")
        if not 200 <= duration <= 10_000:
            raise ValueError("duration_ms must be between 200 and 10000")
        object.__setattr__(self, "duration_ms", duration)
        object.__setattr__(
            self,
            "attack_ratio",
            bounded_number(self.attack_ratio, "attack_ratio", 0.0, 0.45),
        )
        object.__setattr__(
            self,
            "release_ratio",
            bounded_number(self.release_ratio, "release_ratio", 0.0, 0.45),
        )
        if self.attack_ratio + self.release_ratio > 0.9:
            raise ValueError("attack_ratio + release_ratio must not exceed 0.9")


__all__ = [
    "BodyExternalConstraint",
    "BodyPoseAxis",
    "BodyPoseConstraintTarget",
    "BodyPoseDynamicsState",
]
