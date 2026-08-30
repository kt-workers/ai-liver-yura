from datetime import datetime, timezone

import pytest

from app.domain.body import (
    BodyPose,
    BodyVelocity,
    JointTransform,
    JointVelocity,
    Quaternion,
    Vector3,
)
from app.domain.body_realtime.contracts import RealtimeChannel
from app.domain.body_solver import (
    BodyFrameChannelValue,
    BodyMotionExecutionReport,
    BodyMotionExecutionStatus,
    BodyMotionResidual,
    BodyPoseFrame,
    BodySolverFailureCode,
)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _velocity() -> JointVelocity:
    return JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))


def _pose() -> BodyPose:
    return BodyPose(_transform(), (("right_hand", _transform()),))


def _body_velocity() -> BodyVelocity:
    return BodyVelocity(_velocity(), (("right_hand", _velocity()),))


def test_body_pose_frame_keeps_canonical_pose_channels_and_execution_identity() -> None:
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    frame = BodyPoseFrame(
        frame_id="frame-1",
        body_model_id="yura.canonical.v1",
        body_state_revision=4,
        observed_at=now,
        pose=_pose(),
        velocity=_body_velocity(),
        active_plan_id="plan-1",
        active_trajectory_id="trajectory-1",
        channel_values=(
            BodyFrameChannelValue(RealtimeChannel.GAZE_X, -0.25),
            BodyFrameChannelValue(RealtimeChannel.MOUTH_OPENNESS, 0.6),
        ),
        applied_overlay_refs=("overlay-gaze",),
        degraded_overlay_refs=("overlay-sway",),
        trace_id="trace-1",
    )

    value = frame.to_dict()
    assert value["frame_id"] == "frame-1"
    assert value["body_state_revision"] == 4
    assert value["active_trajectory_id"] == "trajectory-1"
    assert value["channel_values"] == [
        {"channel": "gaze_x", "value": -0.25},
        {"channel": "mouth_openness", "value": 0.6},
    ]


def test_body_pose_frame_rejects_duplicate_channels_and_overlay_classification_overlap() -> None:
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="canonical channel"):
        BodyPoseFrame(
            "frame-1",
            "model-1",
            1,
            now,
            _pose(),
            _body_velocity(),
            None,
            None,
            (
                BodyFrameChannelValue(RealtimeChannel.GAZE_X, 0.1),
                BodyFrameChannelValue(RealtimeChannel.GAZE_X, 0.2),
            ),
            (),
            (),
            "trace-1",
        )

    with pytest.raises(ValueError, match="同時"):
        BodyPoseFrame(
            "frame-2",
            "model-1",
            2,
            now,
            _pose(),
            _body_velocity(),
            None,
            None,
            (),
            ("overlay-1",),
            ("overlay-1",),
            "trace-2",
        )


def test_unsigned_canonical_channel_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="負値"):
        BodyFrameChannelValue(RealtimeChannel.MOUTH_OPENNESS, -0.1)


def test_execution_report_does_not_promote_planned_motion_to_actual_completion() -> None:
    planned = BodyMotionExecutionReport(
        plan_id="plan-1",
        trajectory_id="trajectory-1",
        status=BodyMotionExecutionStatus.PLANNED,
    )
    assert planned.started_at is None
    assert planned.completed_at is None

    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="completed_at"):
        BodyMotionExecutionReport(
            plan_id="plan-1",
            trajectory_id="trajectory-1",
            status=BodyMotionExecutionStatus.COMPLETED,
            started_at=now,
        )

    completed = BodyMotionExecutionReport(
        plan_id="plan-1",
        trajectory_id="trajectory-1",
        status=BodyMotionExecutionStatus.COMPLETED,
        started_at=now,
        observable_at=now,
        completed_at=now,
        achieved_target_refs=("goal-1",),
        residuals=(BodyMotionResidual("goal-1", 0.01),),
    )
    assert completed.to_dict()["status"] == "completed"


def test_failure_report_requires_typed_failure_and_forbids_it_on_success() -> None:
    with pytest.raises(ValueError, match="failure_code"):
        BodyMotionExecutionReport(
            plan_id="plan-1",
            trajectory_id="trajectory-1",
            status=BodyMotionExecutionStatus.INFEASIBLE,
        )

    failed = BodyMotionExecutionReport(
        plan_id="plan-1",
        trajectory_id="trajectory-1",
        status=BodyMotionExecutionStatus.INFEASIBLE,
        failure_code=BodySolverFailureCode.INFEASIBLE_TARGET,
    )
    assert failed.to_dict()["failure_code"] == "infeasible_target"

    with pytest.raises(ValueError, match="非failure"):
        BodyMotionExecutionReport(
            plan_id="plan-1",
            trajectory_id="trajectory-1",
            status=BodyMotionExecutionStatus.PLANNED,
            failure_code=BodySolverFailureCode.INFEASIBLE_TARGET,
        )
