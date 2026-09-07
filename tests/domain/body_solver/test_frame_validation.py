from datetime import datetime, timezone

import pytest

from app.domain.body import (
    AnatomicalRegion,
    AnatomicalSide,
    BodyPose,
    BodyVelocity,
    CanonicalBodyModel,
    CenterOfMassReference,
    JointDefinition,
    JointTransform,
    JointVelocity,
    Quaternion,
    Vector3,
)
from app.domain.body_solver import (
    BodyFrameValidationError,
    BodyFrameValidationFailureCode,
    BodyPoseFrame,
    validate_body_pose_frame,
)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _velocity() -> JointVelocity:
    return JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))


def _model() -> CanonicalBodyModel:
    return CanonicalBodyModel(
        body_model_id="yura.canonical.v1",
        joints=(
            JointDefinition(
                joint_id="root",
                parent_joint_id=None,
                region=AnatomicalRegion.ROOT,
                side=AnatomicalSide.CENTER,
                rest_local_transform=_transform(),
                limits=(),
            ),
            JointDefinition(
                joint_id="right_hand",
                parent_joint_id="root",
                region=AnatomicalRegion.HAND,
                side=AnatomicalSide.RIGHT,
                rest_local_transform=_transform(),
                limits=(),
            ),
        ),
        segments=(),
        end_effector_joint_ids=("right_hand",),
        kinematic_chains=(),
        center_of_mass=CenterOfMassReference("root", Vector3(0, 0, 0)),
    )


def _frame(
    *,
    model_id: str = "yura.canonical.v1",
    pose: BodyPose | None = None,
    velocity: BodyVelocity | None = None,
    plan_id: str | None = None,
    trajectory_id: str | None = None,
) -> BodyPoseFrame:
    return BodyPoseFrame(
        frame_id="frame-1",
        body_model_id=model_id,
        body_state_revision=1,
        observed_at=datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc),
        pose=pose or BodyPose(_transform(), (("right_hand", _transform()),)),
        velocity=velocity or BodyVelocity(_velocity(), (("right_hand", _velocity()),)),
        active_plan_id=plan_id,
        active_trajectory_id=trajectory_id,
        channel_values=(),
        applied_overlay_refs=(),
        degraded_overlay_refs=(),
        trace_id="trace-1",
    )


def test_validate_body_pose_frame_accepts_matching_canonical_model() -> None:
    frame = _frame(plan_id="plan-1", trajectory_id="trajectory-1")

    assert validate_body_pose_frame(frame, _model()) is frame


def test_validate_body_pose_frame_rejects_model_identity_mismatch() -> None:
    with pytest.raises(BodyFrameValidationError) as error:
        validate_body_pose_frame(_frame(model_id="other.model"), _model())

    assert error.value.code is BodyFrameValidationFailureCode.MODEL_MISMATCH


def test_validate_body_pose_frame_rejects_skeleton_mismatch() -> None:
    invalid_pose = BodyPose(_transform(), ())
    invalid_velocity = BodyVelocity(_velocity(), ())

    with pytest.raises(BodyFrameValidationError) as error:
        validate_body_pose_frame(
            _frame(pose=invalid_pose, velocity=invalid_velocity),
            _model(),
        )

    assert error.value.code is BodyFrameValidationFailureCode.SKELETON_MISMATCH


def test_validate_body_pose_frame_requires_plan_and_trajectory_identity_pair() -> None:
    with pytest.raises(BodyFrameValidationError) as error:
        validate_body_pose_frame(_frame(plan_id="plan-1"), _model())

    assert error.value.code is BodyFrameValidationFailureCode.MOTION_IDENTITY_MISMATCH
