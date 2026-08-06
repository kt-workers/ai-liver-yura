from __future__ import annotations

from app.domain.body_auxiliary_projection import (
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.domain.body_motion_state import BodyInnerMotionState
from app.domain.body_pose_frame import BodyPoseFrame


def make_body_pose_frame(
    sequence: int,
    *,
    timestamp_ms: int | None = None,
    head_yaw: float = 0.0,
    right_arm_raise: float = 0.0,
    mouth_open: float = 0.0,
) -> BodyPoseFrame:
    """HTTP・SSE統合テスト用の最小BodyPoseFrameを作る。"""

    return BodyPoseFrame(
        sequence=sequence,
        timestamp_ms=timestamp_ms if timestamp_ms is not None else sequence * 100,
        pose=BodyTrackingPose(
            head_yaw=head_yaw,
            right_arm_raise=right_arm_raise,
            mouth_open=mouth_open,
        ),
        velocity=BodyTrackingVelocity(),
        inner_state=BodyInnerMotionState(),
    )
