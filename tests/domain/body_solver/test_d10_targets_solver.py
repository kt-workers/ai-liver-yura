from math import pi, sqrt

import pytest

from app.domain.body import Quaternion, Vector3
from app.domain.body_motion_planning import BodySpatialTarget, BodySpatialTargetKind
from app.domain.body_solver import (
    BodySolveFeasibility,
    BodySolverError,
    BodySolverFailureCode,
    BodySolveTask,
    BodySolveTaskKind,
    BodySpatialTargetSnapshot,
    end_effector_world_frame,
    resolve_body_task_target,
    solve_body_tasks,
    v2_baseline_body_solver_policy,
    validate_tracking_update,
)
from tests.domain.body_solver.d10_fixtures import (
    NOW,
    StaticTargetResolver,
    physical_model,
    physical_state,
    position_snapshot,
    reach_task,
)


def _rotate_forward(rotation: Quaternion) -> Vector3:
    return Vector3(
        2.0 * (rotation.x * rotation.z + rotation.w * rotation.y),
        2.0 * (rotation.y * rotation.z - rotation.w * rotation.x),
        1.0 - 2.0 * (rotation.x * rotation.x + rotation.y * rotation.y),
    )


@pytest.mark.parametrize(
    ("extent", "expected_x", "expected_y"),
    (
        (0.0, 1.0, 0.0),
        (0.5, 0.5, 0.5),
        (1.0, 0.0, 1.0),
    ),
)
def test_target_ref_position_extent_uses_metric_interpolation(
    extent: float,
    expected_x: float,
    expected_y: float,
) -> None:
    model = physical_model()
    state = physical_state()
    task = reach_task(extent=extent)
    resolver = StaticTargetResolver((position_snapshot(pi / 2),))

    target = resolve_body_task_target(task, model, state.pose, resolver)

    assert target.position is not None
    assert target.position.x == pytest.approx(expected_x)
    assert target.position.y == pytest.approx(expected_y)
    assert target.position.z == pytest.approx(0.0)
    assert target.target_ref == "target:hand"
    assert target.target_generation == 1


def test_end_effector_world_frame_uses_explicit_local_offset() -> None:
    frame = end_effector_world_frame(
        physical_model(),
        physical_state().pose,
        "effector:hand",
    )

    assert frame.position == Vector3(1.0, 0.0, 0.0)
    assert frame.forward_axis == Vector3(1.0, 0.0, 0.0)


def test_target_ref_orientation_uses_trusted_snapshot_geometry() -> None:
    model = physical_model()
    state = physical_state()
    orientation = Quaternion(0.0, 0.0, sqrt(0.5), sqrt(0.5))
    snapshot = BodySpatialTargetSnapshot(
        "target:orient",
        None,
        orientation,
        None,
        "test.geometry",
        "geometry:orient",
        1,
        3,
        NOW,
    )
    resolver = StaticTargetResolver((snapshot,))
    task = BodySolveTask(
        "goal:orient",
        BodySolveTaskKind.ORIENTATION_TARGET,
        ("arm", "root"),
        ("chain:arm",),
        BodySpatialTarget(
            BodySpatialTargetKind.TARGET_REF,
            None,
            "target:orient",
            1.0,
        ),
        1.0,
    )

    target = resolve_body_task_target(task, model, state.pose, resolver)

    assert target.orientation == orientation
    assert target.target_ref == "target:orient"
    assert target.target_generation == 3


def test_direction_orientation_extent_uses_shortest_arc_fraction() -> None:
    model = physical_model()
    state = physical_state()
    current = end_effector_world_frame(model, state.pose, "effector:hand")
    assert current.forward_axis == Vector3(1.0, 0.0, 0.0)
    task = BodySolveTask(
        "goal:orient-direction",
        BodySolveTaskKind.ORIENTATION_TARGET,
        ("arm", "root"),
        ("chain:arm",),
        BodySpatialTarget(
            BodySpatialTargetKind.DIRECTION,
            Vector3(0.0, 1.0, 0.0),
            None,
            0.5,
        ),
        1.0,
    )

    target = resolve_body_task_target(
        task,
        model,
        state.pose,
        StaticTargetResolver(()),
    )

    assert target.orientation is not None
    halfway_forward = _rotate_forward(target.orientation)
    assert halfway_forward.x == pytest.approx(sqrt(0.5))
    assert halfway_forward.y == pytest.approx(sqrt(0.5))
    assert halfway_forward.z == pytest.approx(0.0)


def test_chain_direction_translate_uses_explicit_reach_budget() -> None:
    task = BodySolveTask(
        "goal:chain-translate",
        BodySolveTaskKind.POSITION_TARGET,
        ("arm", "root"),
        ("chain:arm",),
        BodySpatialTarget(
            BodySpatialTargetKind.DIRECTION,
            Vector3(0.0, 1.0, 0.0),
            None,
            0.5,
        ),
        1.0,
    )

    target = resolve_body_task_target(
        task,
        physical_model(),
        physical_state().pose,
        StaticTargetResolver(()),
    )

    assert target.position == Vector3(1.0, 0.5, 0.0)


def test_region_only_direction_translate_without_unique_reach_budget_is_unsupported() -> None:
    task = BodySolveTask(
        "goal:ambiguous-translate",
        BodySolveTaskKind.POSITION_TARGET,
        ("arm",),
        (),
        BodySpatialTarget(
            BodySpatialTargetKind.DIRECTION,
            Vector3(0.0, 1.0, 0.0),
            None,
            0.5,
        ),
        1.0,
    )

    with pytest.raises(BodySolverError) as error:
        resolve_body_task_target(
            task,
            physical_model(),
            physical_state().pose,
            StaticTargetResolver(()),
        )

    assert error.value.code is BodySolverFailureCode.UNSUPPORTED_CAPABILITY


def test_root_direction_translate_uses_explicit_root_budget() -> None:
    task = BodySolveTask(
        "goal:root-translate",
        BodySolveTaskKind.POSITION_TARGET,
        ("root",),
        (),
        BodySpatialTarget(
            BodySpatialTargetKind.DIRECTION,
            Vector3(1.0, 0.0, 0.0),
            None,
            0.5,
        ),
        1.0,
    )

    target = resolve_body_task_target(
        task,
        physical_model(),
        physical_state().pose,
        StaticTargetResolver(()),
    )

    assert target.position == Vector3(0.25, 0.0, 0.0)


def test_root_direction_impulse_uses_explicit_velocity_budget() -> None:
    task = BodySolveTask(
        "goal:root-impulse",
        BodySolveTaskKind.ROOT_IMPULSE_TARGET,
        ("root",),
        (),
        BodySpatialTarget(
            BodySpatialTargetKind.DIRECTION,
            Vector3(0.0, 1.0, 0.0),
            None,
            0.5,
        ),
        1.0,
    )

    target = resolve_body_task_target(
        task,
        physical_model(),
        physical_state().pose,
        StaticTargetResolver(()),
    )

    assert target.root_delta_velocity == Vector3(0.0, 0.5, 0.0)


def test_target_ref_unavailable_fails_closed() -> None:
    with pytest.raises(BodySolverError) as error:
        resolve_body_task_target(
            reach_task(),
            physical_model(),
            physical_state().pose,
            StaticTargetResolver(()),
        )

    assert error.value.code is BodySolverFailureCode.TARGET_GEOMETRY_UNAVAILABLE


def test_contact_requires_full_extent() -> None:
    task = BodySolveTask(
        "goal:contact",
        BodySolveTaskKind.CONTACT_TARGET,
        ("arm", "root"),
        ("chain:arm",),
        BodySpatialTarget(
            BodySpatialTargetKind.TARGET_REF,
            None,
            "target:hand",
            0.5,
        ),
        1.0,
    )

    with pytest.raises(BodySolverError) as error:
        resolve_body_task_target(
            task,
            physical_model(),
            physical_state().pose,
            StaticTargetResolver((position_snapshot(0.5),)),
        )

    assert error.value.code is BodySolverFailureCode.CONTACT_INFEASIBLE


def test_tracking_same_generation_remains_valid() -> None:
    previous = position_snapshot(0.2, generation=1)
    current = position_snapshot(0.3, generation=1)

    validate_tracking_update(previous, current)


def test_tracking_generation_change_is_typed_failure() -> None:
    previous = position_snapshot(0.2, generation=1)
    current = position_snapshot(0.3, generation=2)

    with pytest.raises(BodySolverError) as error:
        validate_tracking_update(previous, current)

    assert error.value.code is BodySolverFailureCode.TARGET_GENERATION_CHANGED


def test_scalar_ik_is_deterministic_and_respects_hard_limit() -> None:
    model = physical_model()
    state = physical_state()
    task = reach_task()
    resolver = StaticTargetResolver((position_snapshot(0.6),))
    target = resolve_body_task_target(task, model, state.pose, resolver)
    policy = v2_baseline_body_solver_policy()

    first = solve_body_tasks(model, state, (task,), (target,), policy)
    second = solve_body_tasks(model, state, (task,), (target,), policy)

    assert first == second
    assert first.feasibility is BodySolveFeasibility.FEASIBLE
    assert first.iterations <= policy.max_ik_iterations
    coordinate = first.joint_dof_states[0].coordinates[0]
    assert -1.2 <= coordinate.position_radians <= 1.2
    assert first.residuals[0].position_error_m is not None
    assert first.residuals[0].position_error_m <= policy.position_tolerance_m(
        model.reference_height
    )


def test_unreachable_target_returns_original_state_instead_of_last_iterate() -> None:
    model = physical_model()
    state = physical_state()
    task = reach_task()
    resolver = StaticTargetResolver((position_snapshot(pi),))
    target = resolve_body_task_target(task, model, state.pose, resolver)
    policy = v2_baseline_body_solver_policy()

    solution = solve_body_tasks(model, state, (task,), (target,), policy)

    assert solution.feasibility is BodySolveFeasibility.INFEASIBLE
    assert 0 < solution.iterations <= policy.max_ik_iterations
    assert solution.joint_dof_states == state.joint_dof_states
    assert solution.pose == state.pose
