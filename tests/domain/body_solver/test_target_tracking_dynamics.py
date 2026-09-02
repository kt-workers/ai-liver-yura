from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.body import (
    Axis,
    BodyState,
    JointDofCoordinate,
    JointDofState,
    project_body_pose_from_dof,
)
from app.domain.body_solver.dynamics import advance_joint_dofs, body_velocity_from_dofs
from tests.domain.body_solver.d10_fixtures import physical_model, physical_state


def _target_state(angle: float) -> tuple[JointDofState, ...]:
    return (
        JointDofState(
            "arm",
            (JointDofCoordinate(Axis.Z, angle, 0.0, 0.0),),
        ),
    )


def _state_with_joint_dynamics(
    *,
    angle: float,
    velocity: float,
    acceleration: float,
) -> BodyState:
    model = physical_model()
    base = physical_state(angle=angle)
    dofs = (
        JointDofState(
            "arm",
            (JointDofCoordinate(Axis.Z, angle, velocity, acceleration),),
        ),
    )
    pose = project_body_pose_from_dof(model, base.pose.root_world_transform, dofs)
    body_velocity = body_velocity_from_dofs(
        model,
        dofs,
        base.velocity.root_world_velocity,
        base.velocity,
    )
    return replace(base, pose=pose, velocity=body_velocity, joint_dof_states=dofs)


def _step(state: BodyState, target_angle: float, *, dt: float, revision: int) -> BodyState:
    model = physical_model()
    dofs = advance_joint_dofs(model, state, _target_state(target_angle), dt)
    pose = project_body_pose_from_dof(model, state.pose.root_world_transform, dofs)
    body_velocity = body_velocity_from_dofs(
        model,
        dofs,
        state.velocity.root_world_velocity,
        state.velocity,
    )
    return replace(
        state,
        revision=revision,
        observed_at=state.observed_at + timedelta(seconds=dt),
        pose=pose,
        velocity=body_velocity,
        joint_dof_states=dofs,
    )


def _coordinate(state: BodyState) -> JointDofCoordinate:
    return state.joint_dof_states[0].coordinates[0]


def _assert_dynamic_step(
    previous: JointDofCoordinate,
    current: JointDofCoordinate,
    dt: float,
) -> None:
    dynamic = physical_model().joints[1].dynamic_limits[0]
    jerk = (
        current.acceleration_radians_per_second2
        - previous.acceleration_radians_per_second2
    ) / dt
    assert (
        abs(current.velocity_radians_per_second)
        <= dynamic.max_velocity_radians_per_second + 1e-12
    )
    assert (
        abs(current.acceleration_radians_per_second2)
        <= dynamic.max_acceleration_radians_per_second2 + 1e-12
    )
    assert abs(jerk) <= dynamic.max_jerk_radians_per_second3 + 1e-10


def _run_target(
    state: BodyState,
    target_angle: float,
    *,
    dt: float = 1.0 / 30.0,
    steps: int = 360,
) -> tuple[BodyState, list[float]]:
    positions: list[float] = []
    revision = state.revision
    for _ in range(steps):
        previous = _coordinate(state)
        revision += 1
        state = _step(state, target_angle, dt=dt, revision=revision)
        current = _coordinate(state)
        _assert_dynamic_step(previous, current, dt)
        positions.append(current.position_radians)
    return state, positions


def test_valid_negative_comfortable_target_converges_without_hard_limit_runaway() -> None:
    state, positions = _run_target(physical_state(), -0.65)
    coordinate = _coordinate(state)

    assert min(positions) > -0.8
    assert coordinate.position_radians == pytest.approx(-0.65, abs=1e-3)
    assert abs(coordinate.velocity_radians_per_second) < 1e-3
    assert abs(coordinate.acceleration_radians_per_second2) < 1e-2


def test_valid_positive_target_is_symmetric() -> None:
    state, positions = _run_target(physical_state(), 0.65)
    coordinate = _coordinate(state)

    assert max(positions) < 0.8
    assert coordinate.position_radians == pytest.approx(0.65, abs=1e-3)
    assert abs(coordinate.velocity_radians_per_second) < 1e-3
    assert abs(coordinate.acceleration_radians_per_second2) < 1e-2


@pytest.mark.parametrize(
    ("velocity", "acceleration"),
    ((-0.8, -1.2), (0.8, 1.2)),
)
def test_nonzero_current_dynamics_converge_to_valid_target(
    velocity: float,
    acceleration: float,
) -> None:
    state = _state_with_joint_dynamics(
        angle=0.0,
        velocity=velocity,
        acceleration=acceleration,
    )
    state, positions = _run_target(state, -0.35, steps=420)
    coordinate = _coordinate(state)

    assert min(positions) > -1.0
    assert max(positions) < 1.0
    assert coordinate.position_radians == pytest.approx(-0.35, abs=1e-3)
    assert abs(coordinate.velocity_radians_per_second) < 1e-3


def test_sequential_target_changes_preserve_dynamics_without_hard_limit_conflict() -> None:
    state = physical_state()
    revision = 0
    extrema: list[float] = []
    for target_angle, steps in ((0.35, 18), (-0.35, 18), (-0.65, 360)):
        for _ in range(steps):
            previous = _coordinate(state)
            revision += 1
            state = _step(state, target_angle, dt=1.0 / 30.0, revision=revision)
            current = _coordinate(state)
            _assert_dynamic_step(previous, current, 1.0 / 30.0)
            extrema.append(current.position_radians)

    coordinate = _coordinate(state)
    assert min(extrema) > -0.9
    assert max(extrema) < 0.9
    assert coordinate.position_radians == pytest.approx(-0.65, abs=1e-3)
    assert abs(coordinate.velocity_radians_per_second) < 1e-3
