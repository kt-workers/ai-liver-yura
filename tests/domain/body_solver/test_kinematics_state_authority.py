from datetime import datetime, timedelta, timezone
from math import cos, pi, sin

import pytest

from app.domain.body import (
    AnatomicalRegion,
    AnatomicalSide,
    Axis,
    BodyPose,
    BodyState,
    BodyVelocity,
    CanonicalBodyModel,
    CenterOfMassReference,
    JointDefinition,
    JointLimit,
    JointTransform,
    JointVelocity,
    KinematicChain,
    Quaternion,
    SegmentDefinition,
    Vector3,
)
from app.domain.body_solver import (
    BodySolverFailureCode,
    BodyStateAuthority,
    BodyStateCommitError,
    forward_kinematics,
)


def _identity_transform(*, x: float = 0, y: float = 0, z: float = 0) -> JointTransform:
    return JointTransform(Vector3(x, y, z), Quaternion(0, 0, 0, 1))


def _rotation_z_90() -> Quaternion:
    half = pi / 4
    return Quaternion(0, 0, sin(half), cos(half))


def _zero_velocity() -> JointVelocity:
    return JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))


def _joint(
    joint_id: str,
    parent_joint_id: str | None,
    region: AnatomicalRegion,
    side: AnatomicalSide,
) -> JointDefinition:
    return JointDefinition(
        joint_id=joint_id,
        parent_joint_id=parent_joint_id,
        region=region,
        side=side,
        rest_local_transform=_identity_transform(),
        limits=(JointLimit(Axis.Z, -pi, pi, -pi / 2, pi / 2, 0),),
    )


def _model() -> CanonicalBodyModel:
    return CanonicalBodyModel(
        body_model_id="yura.canonical.v1",
        joints=(
            _joint("root", None, AnatomicalRegion.ROOT, AnatomicalSide.CENTER),
            _joint("right_shoulder", "root", AnatomicalRegion.ARM, AnatomicalSide.RIGHT),
            _joint(
                "right_hand",
                "right_shoulder",
                AnatomicalRegion.HAND,
                AnatomicalSide.RIGHT,
            ),
        ),
        segments=(
            SegmentDefinition("upper_arm", "root", "right_shoulder", 0.3, 0.1),
            SegmentDefinition("forearm", "right_shoulder", "right_hand", 0.3, 0.1),
        ),
        end_effector_joint_ids=("right_hand",),
        kinematic_chains=(
            KinematicChain(
                "right_arm",
                ("root", "right_shoulder", "right_hand"),
                "right_hand",
            ),
        ),
        center_of_mass=CenterOfMassReference("root", Vector3(0, 0, 0)),
    )


def _pose(*, root_rotation: Quaternion | None = None, hand_x: float = 1) -> BodyPose:
    root = JointTransform(Vector3(10, 0, 0), root_rotation or Quaternion(0, 0, 0, 1))
    return BodyPose(
        root_world_transform=root,
        joint_local_transforms=(
            ("right_shoulder", _identity_transform(x=1)),
            ("right_hand", _identity_transform(x=hand_x)),
        ),
    )


def _velocity() -> BodyVelocity:
    return BodyVelocity(
        root_world_velocity=_zero_velocity(),
        joint_local_velocities=(
            ("right_shoulder", _zero_velocity()),
            ("right_hand", _zero_velocity()),
        ),
    )


def _state(revision: int, observed_at: datetime, pose: BodyPose | None = None) -> BodyState:
    return BodyState(
        body_model_id=_model().body_model_id,
        revision=revision,
        observed_at=observed_at,
        pose=pose or _pose(),
        velocity=_velocity(),
    )


def test_forward_kinematics_composes_parent_rotation_and_local_offsets() -> None:
    world = dict(forward_kinematics(_model(), _pose(root_rotation=_rotation_z_90())))

    assert world["root"].position == Vector3(10, 0, 0)
    assert world["right_shoulder"].position.x == pytest.approx(10)
    assert world["right_shoulder"].position.y == pytest.approx(1)
    assert world["right_hand"].position.x == pytest.approx(10)
    assert world["right_hand"].position.y == pytest.approx(2)


def test_forward_kinematics_is_deterministic_for_same_snapshot() -> None:
    model = _model()
    pose = _pose(root_rotation=_rotation_z_90())

    assert forward_kinematics(model, pose) == forward_kinematics(model, pose)


def test_body_state_authority_commits_one_revision_and_returns_matching_frame() -> None:
    now = datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc)
    authority = BodyStateAuthority(_model(), _state(4, now), history_limit=2)
    next_time = now + timedelta(milliseconds=16)

    frame = authority.commit_validated_frame(
        expected_revision=4,
        frame_id="frame-5",
        observed_at=next_time,
        pose=_pose(hand_x=1.1),
        velocity=_velocity(),
        active_plan_id="plan-1",
        active_trajectory_id="trajectory-1",
        channel_values=(),
        applied_overlay_refs=(),
        degraded_overlay_refs=(),
        trace_id="trace-1",
    )

    assert frame.body_state_revision == 5
    assert frame.active_plan_id == "plan-1"
    assert frame.active_trajectory_id == "trajectory-1"
    assert authority.current.revision == 5
    assert authority.current.observed_at == next_time
    assert authority.current.pose == frame.pose
    assert authority.current.history == ((now, _pose()),)


def test_body_state_authority_rejects_stale_writer_and_time_rollback() -> None:
    now = datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc)
    authority = BodyStateAuthority(_model(), _state(1, now))

    with pytest.raises(BodyStateCommitError) as stale:
        authority.commit_validated_frame(
            expected_revision=0,
            frame_id="frame-stale",
            observed_at=now + timedelta(milliseconds=16),
            pose=_pose(),
            velocity=_velocity(),
            active_plan_id=None,
            active_trajectory_id=None,
            channel_values=(),
            applied_overlay_refs=(),
            degraded_overlay_refs=(),
            trace_id="trace-stale",
        )
    assert stale.value.code is BodySolverFailureCode.STALE_HARD_DEPENDENCY

    with pytest.raises(BodyStateCommitError) as rollback:
        authority.commit_validated_frame(
            expected_revision=1,
            frame_id="frame-old-time",
            observed_at=now - timedelta(milliseconds=1),
            pose=_pose(),
            velocity=_velocity(),
            active_plan_id=None,
            active_trajectory_id=None,
            channel_values=(),
            applied_overlay_refs=(),
            degraded_overlay_refs=(),
            trace_id="trace-old-time",
        )
    assert rollback.value.code is BodySolverFailureCode.STALE_HARD_DEPENDENCY
    assert authority.current.revision == 1


def test_body_state_authority_bounds_history_and_requires_plan_trajectory_pair() -> None:
    now = datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc)
    authority = BodyStateAuthority(_model(), _state(0, now), history_limit=1)

    with pytest.raises(ValueError, match="対で"):
        authority.commit_validated_frame(
            expected_revision=0,
            frame_id="frame-invalid",
            observed_at=now + timedelta(milliseconds=16),
            pose=_pose(),
            velocity=_velocity(),
            active_plan_id="plan-1",
            active_trajectory_id=None,
            channel_values=(),
            applied_overlay_refs=(),
            degraded_overlay_refs=(),
            trace_id="trace-invalid",
        )

    first_time = now + timedelta(milliseconds=16)
    authority.commit_validated_frame(
        expected_revision=0,
        frame_id="frame-1",
        observed_at=first_time,
        pose=_pose(hand_x=1.05),
        velocity=_velocity(),
        active_plan_id=None,
        active_trajectory_id=None,
        channel_values=(),
        applied_overlay_refs=(),
        degraded_overlay_refs=(),
        trace_id="trace-1",
    )
    second_time = first_time + timedelta(milliseconds=16)
    authority.commit_validated_frame(
        expected_revision=1,
        frame_id="frame-2",
        observed_at=second_time,
        pose=_pose(hand_x=1.1),
        velocity=_velocity(),
        active_plan_id=None,
        active_trajectory_id=None,
        channel_values=(),
        applied_overlay_refs=(),
        degraded_overlay_refs=(),
        trace_id="trace-2",
    )

    assert authority.current.revision == 2
    assert authority.current.history == ((first_time, _pose(hand_x=1.05)),)
