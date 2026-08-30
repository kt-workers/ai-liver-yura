from __future__ import annotations

from enum import Enum

from app.domain.body import CanonicalBodyModel

from .contracts import BodyPoseFrame


class BodyFrameValidationFailureCode(str, Enum):
    MODEL_MISMATCH = "model_mismatch"
    SKELETON_MISMATCH = "skeleton_mismatch"
    MOTION_IDENTITY_MISMATCH = "motion_identity_mismatch"


class BodyFrameValidationError(ValueError):
    def __init__(self, code: BodyFrameValidationFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


def validate_body_pose_frame(
    frame: BodyPoseFrame,
    model: CanonicalBodyModel,
) -> BodyPoseFrame:
    """Avatar等へ渡す前にframeとCanonical Body Modelの整合をfail-closedで確認する。"""

    if not isinstance(frame, BodyPoseFrame):
        raise ValueError("frame が不正です")
    if not isinstance(model, CanonicalBodyModel):
        raise ValueError("model が不正です")
    if frame.body_model_id != model.body_model_id:
        raise BodyFrameValidationError(BodyFrameValidationFailureCode.MODEL_MISMATCH)
    if (frame.active_plan_id is None) != (frame.active_trajectory_id is None):
        raise BodyFrameValidationError(
            BodyFrameValidationFailureCode.MOTION_IDENTITY_MISMATCH
        )
    try:
        frame.pose.validate_for(model)
        frame.velocity.validate_for(model)
    except ValueError as error:
        raise BodyFrameValidationError(
            BodyFrameValidationFailureCode.SKELETON_MISMATCH
        ) from error
    return frame
