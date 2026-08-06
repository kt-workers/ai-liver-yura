from __future__ import annotations

from dataclasses import dataclass, fields

from app.domain.body_value_validation import bounded_number


@dataclass(frozen=True, slots=True)
class BodyTrackingPose:
    """棒人形／Live2D向けの正規化補助投影。

    汎用3D骨格の代替ではなく、Adapterが必要な場合だけ使用する。
    """

    head_yaw: float = 0.0
    head_pitch: float = 0.0
    head_roll: float = 0.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    eye_left_open: float = 1.0
    eye_right_open: float = 1.0
    mouth_open: float = 0.0
    mouth_form: float = 0.0
    torso_yaw: float = 0.0
    torso_pitch: float = 0.0
    torso_roll: float = 0.0
    body_height: float = 0.0
    left_arm_raise: float = 0.0
    right_arm_raise: float = 0.0
    left_arm_in: float = 0.0
    right_arm_in: float = 0.0

    def __post_init__(self) -> None:
        unit_fields = {
            "eye_left_open",
            "eye_right_open",
            "mouth_open",
            "left_arm_raise",
            "right_arm_raise",
        }
        for value_field in fields(self):
            minimum, maximum = (
                (0.0, 1.0)
                if value_field.name in unit_fields
                else (-1.0, 1.0)
            )
            object.__setattr__(
                self,
                value_field.name,
                bounded_number(
                    getattr(self, value_field.name),
                    value_field.name,
                    minimum,
                    maximum,
                ),
            )

    def as_payload(self) -> dict[str, float]:
        return {
            value_field.name: getattr(self, value_field.name)
            for value_field in fields(self)
        }


@dataclass(frozen=True, slots=True)
class BodyTrackingVelocity:
    """正規化補助軸の毎秒変化量。"""

    head_yaw: float = 0.0
    head_pitch: float = 0.0
    head_roll: float = 0.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    eye_left_open: float = 0.0
    eye_right_open: float = 0.0
    mouth_open: float = 0.0
    mouth_form: float = 0.0
    torso_yaw: float = 0.0
    torso_pitch: float = 0.0
    torso_roll: float = 0.0
    body_height: float = 0.0
    left_arm_raise: float = 0.0
    right_arm_raise: float = 0.0
    left_arm_in: float = 0.0
    right_arm_in: float = 0.0

    def __post_init__(self) -> None:
        for value_field in fields(self):
            object.__setattr__(
                self,
                value_field.name,
                bounded_number(
                    getattr(self, value_field.name),
                    value_field.name,
                    -8.0,
                    8.0,
                ),
            )

    def as_payload(self) -> dict[str, float]:
        return {
            value_field.name: getattr(self, value_field.name)
            for value_field in fields(self)
        }
