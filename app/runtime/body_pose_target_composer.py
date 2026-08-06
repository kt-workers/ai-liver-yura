from __future__ import annotations

from dataclasses import replace

from app.domain.body_auxiliary_projection import BodyTrackingPose
from app.domain.body_expression_input import BodyExpressionInput
from app.domain.body_pose_dynamics import BodyPoseAxis
from app.domain.body_pose_target import BodyPoseTarget
from app.runtime.body_external_constraint_player import (
    BodyExternalConstraintSample,
)
from app.runtime.body_gaze_target_composer import BodyGazeTarget
from app.runtime.body_posture_target_composer import BodyPostureTarget
from app.runtime.body_speech_mouth_driver import BodySpeechMouthSample


class BodyPoseTargetComposer:
    """独立部品の出力を1つの正規化Pose目標へ束ねる。"""

    def compose(
        self,
        *,
        value: BodyExpressionInput,
        gaze: BodyGazeTarget,
        posture: BodyPostureTarget,
        speech: BodySpeechMouthSample,
        constraint: BodyExternalConstraintSample,
        attention_target_id: str | None,
        attention_dwell_ms: int,
    ) -> BodyPoseTarget:
        facial = value.facial_target
        eye_open = self._clamp(
            1.0 + facial.eye_widen * 0.18 - facial.eye_narrow * 0.28,
            0.0,
            1.0,
        )
        mouth_form = self._clamp(facial.smile - facial.frown, -1.0, 1.0)
        surprise_open = value.affect_baseline.surprise * 0.42
        mouth_open = self._clamp(
            max(speech.mouth_open, surprise_open),
            0.0,
            1.0,
        )

        pose = BodyTrackingPose(
            head_yaw=gaze.head_yaw,
            head_pitch=gaze.head_pitch,
            head_roll=gaze.head_roll,
            gaze_x=gaze.gaze_x,
            gaze_y=gaze.gaze_y,
            eye_left_open=eye_open,
            eye_right_open=eye_open,
            mouth_open=mouth_open,
            mouth_form=mouth_form,
            torso_yaw=gaze.torso_yaw,
            torso_pitch=posture.torso_pitch,
            torso_roll=posture.torso_roll,
            body_height=posture.body_height,
            left_arm_raise=posture.left_arm_raise,
            right_arm_raise=posture.right_arm_raise,
            left_arm_in=posture.left_arm_in,
            right_arm_in=posture.right_arm_in,
        )
        pose = self._apply_constraint(pose, constraint)
        return BodyPoseTarget(
            pose=pose,
            facial_target=facial,
            attention_target_id=attention_target_id,
            attention_dwell_ms=attention_dwell_ms,
        )

    def _apply_constraint(
        self,
        pose: BodyTrackingPose,
        sample: BodyExternalConstraintSample,
    ) -> BodyTrackingPose:
        if sample.envelope <= 0.0 or not sample.targets:
            return pose
        changes: dict[str, float] = {}
        for target in sample.targets:
            axis = target.axis
            if not isinstance(axis, BodyPoseAxis):
                continue
            current = getattr(pose, axis.value)
            blend = self._clamp(target.weight * sample.envelope, 0.0, 1.0)
            changes[axis.value] = current * (1.0 - blend) + target.value * blend
        return replace(pose, **changes) if changes else pose

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
