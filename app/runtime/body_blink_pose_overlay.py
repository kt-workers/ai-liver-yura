from __future__ import annotations

from dataclasses import replace

from app.domain.body_pose_dynamics import BodyPoseDynamicsState
from app.domain.body_pose_target import BodyPoseTarget
from app.runtime.body_blink_scheduler import BodyBlinkSample


class BodyBlinkPoseOverlay:
    """積分済み全身Poseへ低遅延の瞬きだけを重ねる。"""

    def apply(
        self,
        *,
        dynamics: BodyPoseDynamicsState,
        target: BodyPoseTarget,
        blink: BodyBlinkSample,
    ) -> BodyPoseDynamicsState:
        if not isinstance(dynamics, BodyPoseDynamicsState):
            raise TypeError("dynamics must be BodyPoseDynamicsState")
        if not isinstance(target, BodyPoseTarget):
            raise TypeError("target must be BodyPoseTarget")
        if not isinstance(blink, BodyBlinkSample):
            raise TypeError("blink must be BodyBlinkSample")
        if not blink.blinking:
            return dynamics

        return replace(
            dynamics,
            pose=replace(
                dynamics.pose,
                eye_left_open=max(
                    0.0,
                    min(1.0, target.pose.eye_left_open * blink.eye_open),
                ),
                eye_right_open=max(
                    0.0,
                    min(1.0, target.pose.eye_right_open * blink.eye_open),
                ),
            ),
        )
