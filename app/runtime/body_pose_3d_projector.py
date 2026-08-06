from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.body_auxiliary_projection import BodyTrackingPose
from app.domain.body_blend_shape import BodyBlendShape, CanonicalBodyBlendShape
from app.domain.body_geometry import (
    BodyGazeVector,
    BodyQuaternion,
    BodyTransform3D,
    BodyVector3,
)
from app.domain.body_skeleton import BodyJointPose, CanonicalBodyJoint


@dataclass(frozen=True, slots=True)
class BodyPose3DProjection:
    root_transform: BodyTransform3D
    joints: tuple[BodyJointPose, ...]
    blend_shapes: tuple[BodyBlendShape, ...]
    gaze_vector: BodyGazeVector


class BodyPose3DProjector:
    """正規化補助PoseをCanonical 3D骨格・BlendShapeへ純粋射影する。"""

    def project(self, pose: BodyTrackingPose) -> BodyPose3DProjection:
        if not isinstance(pose, BodyTrackingPose):
            raise TypeError("pose must be BodyTrackingPose")

        torso_yaw = pose.torso_yaw * math.radians(26.0)
        torso_pitch = pose.torso_pitch * math.radians(22.0)
        torso_roll = pose.torso_roll * math.radians(18.0)
        head_yaw = pose.head_yaw * math.radians(58.0)
        head_pitch = pose.head_pitch * math.radians(38.0)
        head_roll = pose.head_roll * math.radians(28.0)

        joints = (
            BodyJointPose(CanonicalBodyJoint.HIPS.value),
            BodyJointPose(
                CanonicalBodyJoint.SPINE.value,
                BodyQuaternion.from_euler_radians(
                    x=torso_pitch * 0.42,
                    y=torso_yaw * 0.36,
                    z=torso_roll * 0.34,
                ),
            ),
            BodyJointPose(
                CanonicalBodyJoint.CHEST.value,
                BodyQuaternion.from_euler_radians(
                    x=torso_pitch * 0.58,
                    y=torso_yaw * 0.64,
                    z=torso_roll * 0.66,
                ),
            ),
            BodyJointPose(
                CanonicalBodyJoint.NECK.value,
                BodyQuaternion.from_euler_radians(
                    x=head_pitch * 0.28,
                    y=head_yaw * 0.24,
                    z=head_roll * 0.22,
                ),
            ),
            BodyJointPose(
                CanonicalBodyJoint.HEAD.value,
                BodyQuaternion.from_euler_radians(
                    x=head_pitch * 0.72,
                    y=head_yaw * 0.76,
                    z=head_roll * 0.78,
                ),
            ),
            BodyJointPose(
                CanonicalBodyJoint.LEFT_UPPER_ARM.value,
                BodyQuaternion.from_euler_radians(
                    x=-pose.left_arm_in * math.radians(24.0),
                    z=-pose.left_arm_raise * math.radians(112.0),
                ),
            ),
            BodyJointPose(
                CanonicalBodyJoint.RIGHT_UPPER_ARM.value,
                BodyQuaternion.from_euler_radians(
                    x=pose.right_arm_in * math.radians(24.0),
                    z=pose.right_arm_raise * math.radians(112.0),
                ),
            ),
            BodyJointPose(CanonicalBodyJoint.LEFT_LOWER_ARM.value),
            BodyJointPose(CanonicalBodyJoint.RIGHT_LOWER_ARM.value),
        )
        blend_shapes = (
            BodyBlendShape(
                CanonicalBodyBlendShape.EYE_BLINK_LEFT.value,
                1.0 - pose.eye_left_open,
            ),
            BodyBlendShape(
                CanonicalBodyBlendShape.EYE_BLINK_RIGHT.value,
                1.0 - pose.eye_right_open,
            ),
            BodyBlendShape(
                CanonicalBodyBlendShape.JAW_OPEN.value,
                pose.mouth_open,
            ),
            BodyBlendShape(
                CanonicalBodyBlendShape.MOUTH_SMILE.value,
                max(0.0, pose.mouth_form),
            ),
            BodyBlendShape(
                CanonicalBodyBlendShape.MOUTH_FROWN.value,
                max(0.0, -pose.mouth_form),
            ),
        )
        gaze_direction = BodyVector3(
            pose.gaze_x * 0.62,
            -pose.gaze_y * 0.48,
            1.0,
        ).normalized()
        return BodyPose3DProjection(
            root_transform=BodyTransform3D(
                position=BodyVector3(0.0, pose.body_height * 0.085, 0.0),
            ),
            joints=joints,
            blend_shapes=blend_shapes,
            gaze_vector=BodyGazeVector(direction=gaze_direction),
        )
