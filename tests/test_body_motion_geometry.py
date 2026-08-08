from __future__ import annotations

import math

import pytest

from app.domain.body_geometry import BodyGazeVector, BodyQuaternion, BodyVector3
from app.domain.body_motion_goal import BodyMotionGoal, BodyMotionGoalKind


def assert_vector_close(
    actual: BodyVector3,
    expected: BodyVector3,
    *,
    abs_tol: float = 1e-7,
) -> None:
    assert actual.x == pytest.approx(expected.x, abs=abs_tol)
    assert actual.y == pytest.approx(expected.y, abs=abs_tol)
    assert actual.z == pytest.approx(expected.z, abs=abs_tol)


@pytest.mark.parametrize(
    "direction",
    [
        BodyVector3(1.0, 0.0, 0.0),
        BodyVector3(-1.0, 0.0, 0.0),
        BodyVector3(0.0, 1.0, 0.0),
        BodyVector3(0.0, -1.0, 0.0),
        BodyVector3(0.0, 0.0, 1.0),
        BodyVector3(0.0, 0.0, -1.0),
        BodyVector3(1.0, 1.0, 1.0),
        BodyVector3(-2.0, 3.0, -4.0),
    ],
)
def test_look_direction_accepts_full_3d_unit_sphere(direction: BodyVector3) -> None:
    goal = BodyMotionGoal(
        kind=BodyMotionGoalKind.LOOK_DIRECTION,
        direction=direction,
    )

    assert goal.direction is not None
    assert goal.direction.length == pytest.approx(1.0)
    assert_vector_close(goal.direction, direction.normalized())


def test_gaze_vector_preserves_vertical_and_depth_components() -> None:
    gaze = BodyGazeVector(direction=BodyVector3(-2.0, 3.0, -4.0))

    assert gaze.direction.length == pytest.approx(1.0)
    assert gaze.direction.x < 0.0
    assert gaze.direction.y > 0.0
    assert gaze.direction.z < 0.0


def test_quaternion_rotates_forward_to_full_3d_target_direction() -> None:
    forward = BodyVector3(0.0, 0.0, 1.0)
    target = BodyVector3(1.0, -2.0, -3.0).normalized()
    rotation = BodyQuaternion.from_two_vectors(forward, target)

    rotated = rotation.rotate_vector(forward).normalized()

    assert_vector_close(rotated, target)


def test_quaternion_handles_exact_opposite_direction() -> None:
    forward = BodyVector3(0.0, 0.0, 1.0)
    backward = BodyVector3(0.0, 0.0, -1.0)
    rotation = BodyQuaternion.from_two_vectors(forward, backward)

    rotated = rotation.rotate_vector(forward).normalized()

    assert_vector_close(rotated, backward)


def test_joint_orientation_uses_quaternion_not_2d_axis_preset() -> None:
    orientation = BodyQuaternion.from_axis_angle(
        BodyVector3(1.0, 1.0, 1.0),
        math.radians(73.0),
    )
    goal = BodyMotionGoal(
        kind=BodyMotionGoalKind.JOINT_ORIENTATION,
        target_id="head",
        orientation=orientation,
    )

    assert goal.orientation == orientation
    assert goal.orientation is not None
    assert math.sqrt(
        goal.orientation.x**2
        + goal.orientation.y**2
        + goal.orientation.z**2
        + goal.orientation.w**2
    ) == pytest.approx(1.0)


def test_zero_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="zero vector"):
        BodyMotionGoal(
            kind=BodyMotionGoalKind.LOOK_DIRECTION,
            direction=BodyVector3(),
        )
