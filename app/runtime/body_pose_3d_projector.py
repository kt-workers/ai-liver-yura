from __future__ import annotations

import math
from dataclasses import replace

from app.domain.body_pose_frame import (
    BodyBlendShape,
    BodyGazeVector,
    BodyJointPose,
    BodyPoseFrame,
    BodyQuaternion,
    BodyTransform3D,
    BodyVector3,
)
from app.runtime.procedural_body_controller import ProceduralBodyController


class BodyPose3DProjector:
    """正規化補助軸をCanonical 3D骨格・BlendShapeへ投影する。

    モデル固有の骨名やVRM／Live2D Parameter名はここへ入れない。Avatar Adapterが
    canonical joint_idとblend shape名を対象モデルへ割り当てる。
    """

    def project(self, frame: BodyPoseFrame) -> BodyPoseFrame:
        pose = frame.pose
        torso_yaw = pose.torso_yaw * math.radians(26.0)
        torso_pitch = pose.torso_pitch * math.radians(22.0)
        torso_roll = pose.torso_roll * math.radians(18.0)
        head_yaw = pose.head_yaw * math.radians(58.0)
        head_pitch = pose.head_pitch * math.radians(38.0)
        head_roll = pose.head_roll * math.radians(28.0)

        joints = (
            BodyJointPose("hips"),
            BodyJointPose(
                "spine",
                BodyQuaternion.from_euler_radians(
                    x=torso_pitch * 0.42,
                    y=torso_yaw * 0.36,
                    z=torso_roll * 0.34,
                ),
            ),
            BodyJointPose(
                "chest",
                BodyQuaternion.from_euler_radians(
                    x=torso_pitch * 0.58,
                    y=torso_yaw * 0.64,
                    z=torso_roll * 0.66,
                ),
            ),
            BodyJointPose(
                "neck",
                BodyQuaternion.from_euler_radians(
                    x=head_pitch * 0.28,
                    y=head_yaw * 0.24,
                    z=head_roll * 0.22,
                ),
            ),
            BodyJointPose(
                "head",
                BodyQuaternion.from_euler_radians(
                    x=head_pitch * 0.72,
                    y=head_yaw * 0.76,
                    z=head_roll * 0.78,
                ),
            ),
            BodyJointPose(
                "left_upper_arm",
                BodyQuaternion.from_euler_radians(
                    x=-pose.left_arm_in * math.radians(24.0),
                    z=-pose.left_arm_raise * math.radians(112.0),
                ),
            ),
            BodyJointPose(
                "right_upper_arm",
                BodyQuaternion.from_euler_radians(
                    x=pose.right_arm_in * math.radians(24.0),
                    z=pose.right_arm_raise * math.radians(112.0),
                ),
            ),
            BodyJointPose("left_lower_arm"),
            BodyJointPose("right_lower_arm"),
        )
        blend_shapes = (
            BodyBlendShape("eye_blink_left", 1.0 - pose.eye_left_open),
            BodyBlendShape("eye_blink_right", 1.0 - pose.eye_right_open),
            BodyBlendShape("jaw_open", pose.mouth_open),
            BodyBlendShape("mouth_smile", max(0.0, pose.mouth_form)),
            BodyBlendShape("mouth_frown", max(0.0, -pose.mouth_form)),
        )
        gaze_direction = BodyVector3(
            pose.gaze_x * 0.62,
            -pose.gaze_y * 0.48,
            1.0,
        ).normalized()
        root = BodyTransform3D(
            position=BodyVector3(0.0, pose.body_height * 0.085, 0.0),
        )
        return replace(
            frame,
            root_transform=root,
            joints=joints,
            blend_shapes=blend_shapes,
            gaze_vector=BodyGazeVector(direction=gaze_direction),
        )


class KinematicProceduralBodyController(ProceduralBodyController):
    """連続Controllerの出力を2D補助軸と3D骨格の両方で返す。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._body_pose_3d_projector = BodyPose3DProjector()

    def tick(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyPoseFrame:
        frame = super().tick(
            timestamp_ms=timestamp_ms,
            dt_seconds=dt_seconds,
        )
        return self._body_pose_3d_projector.project(frame)
