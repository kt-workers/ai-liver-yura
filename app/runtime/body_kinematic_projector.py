from __future__ import annotations

import math

from app.domain.body_kinematics import (
    BodyKinematicJoint,
    BodyKinematicPoint,
    BodyKinematicPose,
)
from app.domain.body_pose_frame import BodyTrackingPose


class BodyKinematicProjector:
    """正規化補助軸をモデル非依存のCanonical関節位置へ投影する。"""

    _UPPER_ARM_LENGTH = 0.38
    _LOWER_ARM_LENGTH = 0.36
    _UPPER_LEG_LENGTH = 0.55
    _LOWER_LEG_LENGTH = 0.55

    def project(self, pose: BodyTrackingPose) -> BodyKinematicPose:
        root = BodyKinematicPoint(0.0, pose.body_height * 0.12, 0.0)
        pelvis = BodyKinematicPoint(0.0, 0.0, 0.0)
        torso_shift = pose.torso_roll * 0.10
        spine = BodyKinematicPoint(torso_shift * 0.35, 0.34, 0.0)
        chest = BodyKinematicPoint(torso_shift, 0.70, -pose.torso_pitch * 0.04)
        neck = BodyKinematicPoint(
            chest.x + pose.head_roll * 0.035,
            0.91,
            chest.z,
        )
        head = BodyKinematicPoint(
            neck.x + pose.head_yaw * 0.045,
            1.15 - pose.head_pitch * 0.035,
            neck.z + pose.head_pitch * 0.025,
        )

        shoulder_y = 0.73
        left_shoulder = BodyKinematicPoint(chest.x - 0.32, shoulder_y, chest.z)
        right_shoulder = BodyKinematicPoint(chest.x + 0.32, shoulder_y, chest.z)
        left_elbow, left_hand = self._arm_chain(
            left_shoulder,
            side=-1,
            raise_amount=pose.left_arm_raise,
            inward=pose.left_arm_in,
        )
        right_elbow, right_hand = self._arm_chain(
            right_shoulder,
            side=1,
            raise_amount=pose.right_arm_raise,
            inward=pose.right_arm_in,
        )

        left_hip = BodyKinematicPoint(-0.18, 0.0, 0.0)
        right_hip = BodyKinematicPoint(0.18, 0.0, 0.0)
        left_knee = BodyKinematicPoint(-0.19, -self._UPPER_LEG_LENGTH, 0.0)
        right_knee = BodyKinematicPoint(0.19, -self._UPPER_LEG_LENGTH, 0.0)
        left_ankle = BodyKinematicPoint(-0.20, -1.10, 0.0)
        right_ankle = BodyKinematicPoint(0.20, -1.10, 0.0)

        joints = (
            BodyKinematicJoint("pelvis", pelvis),
            BodyKinematicJoint("spine", spine),
            BodyKinematicJoint("chest", chest),
            BodyKinematicJoint("neck", neck),
            BodyKinematicJoint("head", head),
            BodyKinematicJoint("left_shoulder", left_shoulder),
            BodyKinematicJoint("left_elbow", left_elbow),
            BodyKinematicJoint("left_hand", left_hand),
            BodyKinematicJoint("right_shoulder", right_shoulder),
            BodyKinematicJoint("right_elbow", right_elbow),
            BodyKinematicJoint("right_hand", right_hand),
            BodyKinematicJoint("left_hip", left_hip),
            BodyKinematicJoint("left_knee", left_knee),
            BodyKinematicJoint("left_ankle", left_ankle),
            BodyKinematicJoint("right_hip", right_hip),
            BodyKinematicJoint("right_knee", right_knee),
            BodyKinematicJoint("right_ankle", right_ankle),
        )
        return BodyKinematicPose(joints=joints, root_position=root)

    def _arm_chain(
        self,
        shoulder: BodyKinematicPoint,
        *,
        side: int,
        raise_amount: float,
        inward: float,
    ) -> tuple[BodyKinematicPoint, BodyKinematicPoint]:
        # neutralは肩から斜め下。raise=1で肩の外側を通り頭上へ到達する。
        neutral_angle = math.radians(-60.0 if side > 0 else -120.0)
        raised_angle = math.radians(92.0)
        amount = max(0.0, min(1.0, raise_amount))
        angle = neutral_angle + self._shortest_angle(neutral_angle, raised_angle) * amount
        angle -= side * inward * math.radians(20.0)
        elbow = BodyKinematicPoint(
            shoulder.x + math.cos(angle) * self._UPPER_ARM_LENGTH,
            shoulder.y + math.sin(angle) * self._UPPER_ARM_LENGTH,
            shoulder.z,
        )
        elbow_bend = math.radians(8.0 + abs(inward) * 24.0 + amount * 8.0)
        lower_angle = angle + side * elbow_bend
        hand = BodyKinematicPoint(
            elbow.x + math.cos(lower_angle) * self._LOWER_ARM_LENGTH,
            elbow.y + math.sin(lower_angle) * self._LOWER_ARM_LENGTH,
            elbow.z,
        )
        return elbow, hand

    @staticmethod
    def _shortest_angle(start: float, end: float) -> float:
        delta = (end - start + math.pi) % (2.0 * math.pi) - math.pi
        return delta
