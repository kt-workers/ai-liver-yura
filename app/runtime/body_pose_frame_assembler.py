from __future__ import annotations

from app.domain.body_blend_shape import BodyBlendShape
from app.domain.body_motion_state import BodyInnerMotionState
from app.domain.body_pose_dynamics import BodyPoseDynamicsState
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.body_pose_target import BodyPoseTarget
from app.runtime.body_pose_3d_projector import BodyPose3DProjector


class BodyPoseFrameAssembler:
    """積分済みPoseと意味的顔ターゲットからBodyPoseFrameを組み立てる。"""

    def __init__(self, projector: BodyPose3DProjector | None = None) -> None:
        self._projector = projector or BodyPose3DProjector()

    def assemble(
        self,
        *,
        sequence: int,
        timestamp_ms: int,
        dynamics: BodyPoseDynamicsState,
        inner_state: BodyInnerMotionState,
        target: BodyPoseTarget,
    ) -> BodyPoseFrame:
        if not isinstance(dynamics, BodyPoseDynamicsState):
            raise TypeError("dynamics must be BodyPoseDynamicsState")
        if not isinstance(inner_state, BodyInnerMotionState):
            raise TypeError("inner_state must be BodyInnerMotionState")
        if not isinstance(target, BodyPoseTarget):
            raise TypeError("target must be BodyPoseTarget")

        projection = self._projector.project(dynamics.pose)
        facial = target.facial_target
        expression_shapes = (
            BodyBlendShape("brow_raise", facial.brow_raise),
            BodyBlendShape("brow_lower", facial.brow_tension),
            BodyBlendShape("eye_squint_left", facial.eye_narrow),
            BodyBlendShape("eye_squint_right", facial.eye_narrow),
            BodyBlendShape("mouth_tension", facial.mouth_tension),
        )
        return BodyPoseFrame(
            sequence=sequence,
            timestamp_ms=timestamp_ms,
            pose=dynamics.pose,
            velocity=dynamics.velocity,
            inner_state=inner_state,
            root_transform=projection.root_transform,
            joints=projection.joints,
            blend_shapes=projection.blend_shapes + expression_shapes,
            gaze_vector=projection.gaze_vector,
            attention_target_id=target.attention_target_id,
            attention_dwell_ms=target.attention_dwell_ms,
        )
