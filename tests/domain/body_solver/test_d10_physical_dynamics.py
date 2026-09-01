from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.body import (
    Axis,
    BodyPose,
    BodyState,
    JointDofCoordinate,
    JointDofState,
    JointTransform,
    Quaternion,
    SegmentDefinition,
    Vector3,
    project_body_pose_from_dof,
)
from app.domain.body_motion_planning import BodyBalanceMode
from app.domain.body_solver import (
    BodySolverError,
    BodySolverFailureCode,
    dynamic_center_of_mass,
    validate_balance,
    v2_baseline_body_solver_policy,
)
from app.domain.body_solver.dynamics import advance_joint_dofs, body_velocity_from_dofs
from tests.domain.body_solver.d10_fixtures import (
    NOW,
    SUPPORT_CONTACT_IDS,
    physical_model,
    physical_state,
)


def _pose_with_arm_offset(x: float) -> BodyPose:
    state = physical_state()
    return BodyPose(
        state.pose.root_world_transform,
        (
            (
                "arm",
                JointTransform(Vector3(x, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0)),
            ),
        ),
    )


def test_dynamic_center_of_mass_uses_explicit_segment_fraction() -> None:
    model = replace(
        physical_model(),
        segments=(
            SegmentDefinition(
                "segment:arm",
                "root",
                "arm",
                1.0,
                1.0,
                0.5,
            ),
        ),
    )

    center = dynamic_center_of_mass(model, _pose_with_arm_offset(1.0))

    assert center.x == pytest.approx(0.5)
    assert center.y == pytest.approx(0.0)
    assert center.z == pytest.approx(0.0)


def test_grounded_balance_accepts_com_inside_support_polygon() -> None:
    model = physical_model()
    evidence = validate_balance(
        model,
        physical_state().pose,
        BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
        SUPPORT_CONTACT_IDS,
        v2_baseline_body_solver_policy(),
    )

    assert evidence.grounded_requirement_applied is True
    assert evidence.active_support_contact_ids == SUPPORT_CONTACT_IDS
    assert len(evidence.support_polygon_xz) == 3
    assert evidence.support_margin_m is not None
    assert evidence.support_margin_m > 0


def test_grounded_balance_fails_closed_for_insufficient_support_geometry() -> None:
    with pytest.raises(BodySolverError) as error:
        validate_balance(
            physical_model(),
            physical_state().pose,
            BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
            SUPPORT_CONTACT_IDS[:2],
            v2_baseline_body_solver_policy(),
        )

    assert error.value.code is BodySolverFailureCode.INSUFFICIENT_SUPPORT_GEOMETRY


def test_grounded_balance_rejects_com_outside_support_polygon() -> None:
    model = replace(
        physical_model(),
        segments=(
            SegmentDefinition(
                "segment:arm",
                "root",
                "arm",
                1.0,
                1.0,
                1.0,
            ),
        ),
    )

    with pytest.raises(BodySolverError) as error:
        validate_balance(
            model,
            _pose_with_arm_offset(1.0),
            BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
            SUPPORT_CONTACT_IDS,
            v2_baseline_body_solver_policy(),
        )

    assert error.value.code is BodySolverFailureCode.BALANCE_INFEASIBLE


def test_temporary_flight_releases_support_and_recovery_requires_it_again() -> None:
    model = physical_model()
    pose = physical_state().pose
    policy = v2_baseline_body_solver_policy()

    airborne = validate_balance(
        model,
        pose,
        BodyBalanceMode.TEMPORARY_FLIGHT_ALLOWED,
        (),
        policy,
    )
    recovered = validate_balance(
        model,
        pose,
        BodyBalanceMode.RECOVER_STABLE_SUPPORT,
        SUPPORT_CONTACT_IDS,
        policy,
    )

    assert airborne.grounded_requirement_applied is False
    assert airborne.active_support_contact_ids == ()
    assert recovered.grounded_requirement_applied is True


def test_joint_tick_bounds_velocity_acceleration_and_jerk_across_frames() -> None:
    model = physical_model()
    state = physical_state()
    dt = 1.0 / 60.0
    target_states = (
        JointDofState(
            "arm",
            (JointDofCoordinate(Axis.Z, 1.0, 0.0, 0.0),),
        ),
    )
    definition = next(item for item in model.joints if item.joint_id == "arm")
    dynamic = definition.dynamic_limits[0]
    previous_acceleration = 0.0

    for revision in range(1, 7):
        next_dofs = advance_joint_dofs(model, state, target_states, dt)
        coordinate = next_dofs[0].coordinates[0]
        jerk = (coordinate.acceleration_radians_per_second2 - previous_acceleration) / dt
        assert abs(coordinate.velocity_radians_per_second) <= pytest.approx(
            dynamic.max_velocity_radians_per_second
        )
        assert abs(coordinate.acceleration_radians_per_second2) <= pytest.approx(
            dynamic.max_acceleration_radians_per_second2
        )
        assert abs(jerk) <= pytest.approx(dynamic.max_jerk_radians_per_second3)

        next_pose = project_body_pose_from_dof(
            model,
            state.pose.root_world_transform,
            next_dofs,
        )
        next_velocity = body_velocity_from_dofs(
            model,
            next_dofs,
            state.velocity.root_world_velocity,
            state.velocity,
        )
        state = BodyState(
            model.body_model_id,
            revision,
            NOW + timedelta(seconds=revision * dt),
            next_pose,
            next_velocity,
            body_model_revision=model.body_model_revision,
            body_model_fingerprint=model.body_model_fingerprint,
            joint_dof_states=next_dofs,
        )
        previous_acceleration = coordinate.acceleration_radians_per_second2
