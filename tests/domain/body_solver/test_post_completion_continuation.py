from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.body import (
    BodyVelocity,
    CanonicalBodyModel,
    JointVelocity,
    Vector3,
    project_body_pose_from_dof,
)
from app.domain.body_realtime import (
    ChannelOverlay,
    RealtimeChannel,
    RealtimeLayer,
    RealtimeLayerState,
    RealtimeLayerStatus,
    RealtimeOverlayBundle,
)
from app.domain.body_solver import (
    BodyContinuousController,
    BodyControllerTickResult,
    BodyMotionExecutionStatus,
    BodySolverError,
    BodySolverFailureCode,
    BodyStateAuthority,
    v2_baseline_body_solver_policy,
)
from tests.domain.body_solver.d10_fixtures import (
    NOW,
    SUPPORT_CONTACT_IDS,
    StaticTargetResolver,
    physical_model,
    physical_state,
    position_snapshot,
    reach_task,
    trajectory_for,
)


def _layer_states() -> tuple[RealtimeLayerState, ...]:
    return tuple(
        RealtimeLayerState(layer, RealtimeLayerStatus.ACTIVE)
        for layer in RealtimeLayer
    )


def _overlay(revision: int) -> RealtimeOverlayBundle:
    return RealtimeOverlayBundle(
        "overlay:baseline",
        revision,
        None,
        None,
        None,
        NOW,
        16.0,
        0.0,
        (
            ChannelOverlay(
                "overlay:gaze",
                RealtimeLayer.GAZE,
                RealtimeChannel.GAZE_X,
                0.4,
                1.0,
                50,
            ),
        ),
        _layer_states(),
    )


def _resolver() -> StaticTargetResolver:
    return StaticTargetResolver(
        (
            position_snapshot(0.8, target_ref="target:old"),
            position_snapshot(-0.8, target_ref="target:new"),
        )
    )


def _old_trajectory():
    return trajectory_for(
        reach_task(extent=0.0, target_ref="target:old"),
        trajectory_id="trajectory:old",
        plan_id="plan:old",
        duration_s=0.01,
    )


def _controller(
    *,
    initial_angle: float = 0.0,
) -> tuple[BodyStateAuthority, StaticTargetResolver, BodyContinuousController]:
    model = physical_model()
    authority = BodyStateAuthority(model, physical_state(angle=initial_angle))
    resolver = _resolver()
    controller = BodyContinuousController(
        model,
        v2_baseline_body_solver_policy(),
        _old_trajectory(),
        authority,
        resolver,
        started_monotonic_s=100.0,
    )
    return authority, resolver, controller


def _moving_controller() -> tuple[
    CanonicalBodyModel,
    BodyStateAuthority,
    StaticTargetResolver,
    BodyContinuousController,
]:
    model = physical_model()
    base = physical_state(angle=0.4)
    coordinate = base.joint_dof_states[0].coordinates[0]
    moving_coordinate = replace(
        coordinate,
        velocity_radians_per_second=0.03,
        acceleration_radians_per_second2=0.0,
    )
    moving_dof = replace(
        base.joint_dof_states[0],
        coordinates=(moving_coordinate,),
    )
    moving_pose = project_body_pose_from_dof(
        model,
        base.pose.root_world_transform,
        (moving_dof,),
    )
    moving_velocity = BodyVelocity(
        JointVelocity(Vector3(0.03, 0, 0), Vector3(0, 0, 0)),
        (
            (
                "arm",
                JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0.03)),
            ),
        ),
    )
    moving_state = replace(
        base,
        pose=moving_pose,
        velocity=moving_velocity,
        joint_dof_states=(moving_dof,),
    )
    authority = BodyStateAuthority(model, moving_state)
    resolver = _resolver()
    controller = BodyContinuousController(
        model,
        v2_baseline_body_solver_policy(),
        _old_trajectory(),
        authority,
        resolver,
        started_monotonic_s=100.0,
    )
    return model, authority, resolver, controller


def _tick(
    controller: BodyContinuousController,
    *,
    index: int,
    monotonic_s: float,
    supports: tuple[str, ...] = SUPPORT_CONTACT_IDS,
    overlay: RealtimeOverlayBundle | None = None,
) -> BodyControllerTickResult:
    return controller.tick(
        observed_at=NOW + timedelta(milliseconds=20 * index),
        monotonic_now_s=monotonic_s,
        active_support_contact_ids=supports,
        overlay_bundle=overlay,
        frame_id=f"frame:post-completion:{index}",
        trace_id=f"trace:post-completion:{index}",
    )


def _complete(controller: BodyContinuousController) -> None:
    first = _tick(controller, index=1, monotonic_s=100.0)
    assert first.execution_report.status is BodyMotionExecutionStatus.OBSERVABLE
    completed = _tick(controller, index=2, monotonic_s=100.02)
    assert completed.execution_report.status is BodyMotionExecutionStatus.COMPLETED


def test_completed_motion_continues_baseline_with_realtime_overlay() -> None:
    authority, _, controller = _controller(initial_angle=0.4)
    _complete(controller)
    completed_report = controller.execution_report
    completed_state = authority.current
    completed_coordinate = completed_state.joint_dof_states[0].coordinates[0]

    baseline = _tick(
        controller,
        index=3,
        monotonic_s=100.04,
        overlay=_overlay(completed_state.revision),
    )

    assert baseline.phase_id == "baseline:continuation"
    assert baseline.frame.body_state_revision == completed_state.revision + 1
    assert baseline.frame.active_plan_id is None
    assert baseline.frame.active_trajectory_id is None
    assert baseline.execution_report == completed_report
    assert baseline.execution_report.status is BodyMotionExecutionStatus.COMPLETED
    assert baseline.execution_report.completed_at == completed_report.completed_at
    assert baseline.execution_report.residuals == completed_report.residuals
    assert baseline.frame.channel_values[0].channel is RealtimeChannel.GAZE_X
    assert baseline.frame.channel_values[0].value == pytest.approx(0.4)
    assert baseline.frame.applied_overlay_refs == ("overlay:gaze",)
    assert baseline.frame.degraded_overlay_refs == ()
    baseline_coordinate = authority.current.joint_dof_states[0].coordinates[0]
    assert baseline_coordinate.position_radians == pytest.approx(
        completed_coordinate.position_radians
    )
    assert baseline_coordinate.position_radians > 0.39


def test_completed_baseline_settles_dynamic_state_within_bounds() -> None:
    model, authority, _, controller = _moving_controller()
    _complete(controller)
    before = authority.current
    before_coordinate = before.joint_dof_states[0].coordinates[0]
    before_root = before.velocity.root_world_velocity.linear
    dt = 0.02

    _tick(controller, index=3, monotonic_s=100.04)

    after = authority.current
    after_coordinate = after.joint_dof_states[0].coordinates[0]
    after_root = after.velocity.root_world_velocity.linear
    arm = next(joint for joint in model.joints if joint.joint_id == "arm")
    dynamic = arm.dynamic_limits[0]
    root_dynamic = model.root_dynamic_limit
    assert root_dynamic is not None

    assert abs(after_coordinate.velocity_radians_per_second) < abs(
        before_coordinate.velocity_radians_per_second
    )
    assert abs(
        after_coordinate.position_radians - before_coordinate.position_radians
    ) <= dynamic.max_velocity_radians_per_second * dt + 1e-12
    assert abs(
        after_coordinate.velocity_radians_per_second
        - before_coordinate.velocity_radians_per_second
    ) <= dynamic.max_acceleration_radians_per_second2 * dt + 1e-12
    assert abs(
        after_coordinate.acceleration_radians_per_second2
        - before_coordinate.acceleration_radians_per_second2
    ) <= dynamic.max_jerk_radians_per_second3 * dt + 1e-12
    root_velocity_delta = Vector3(
        after_root.x - before_root.x,
        after_root.y - before_root.y,
        after_root.z - before_root.z,
    )
    assert after_root.magnitude < before_root.magnitude
    assert (
        root_velocity_delta.magnitude
        <= root_dynamic.max_linear_acceleration_mps2 * dt + 1e-12
    )
    assert after_root.magnitude <= root_dynamic.max_linear_velocity_mps


def test_completed_baseline_stale_overlay_is_degraded() -> None:
    authority, _, controller = _controller()
    _complete(controller)
    assert authority.current.revision > 0

    baseline = _tick(
        controller,
        index=3,
        monotonic_s=100.04,
        overlay=_overlay(0),
    )

    assert baseline.frame.channel_values == ()
    assert baseline.frame.applied_overlay_refs == ()
    assert baseline.frame.degraded_overlay_refs == ("overlay:gaze",)


def test_completed_baseline_balance_failure_is_atomic() -> None:
    authority, _, controller = _controller()
    _complete(controller)
    revision = authority.current.revision
    completed_report = controller.execution_report

    with pytest.raises(BodySolverError) as error:
        _tick(
            controller,
            index=3,
            monotonic_s=100.04,
            supports=SUPPORT_CONTACT_IDS[:2],
        )
    assert error.value.code is BodySolverFailureCode.INSUFFICIENT_SUPPORT_GEOMETRY
    assert authority.current.revision == revision
    assert controller.execution_report == completed_report

    retry = _tick(controller, index=3, monotonic_s=100.04)
    assert retry.frame.body_state_revision == revision + 1
    assert retry.execution_report == completed_report


def test_completed_trajectory_can_activate_new_trajectory_on_same_controller() -> None:
    authority, _, controller = _controller()
    _complete(controller)
    completed_report = controller.execution_report
    completed_state = authority.current
    new_trajectory = trajectory_for(
        reach_task(extent=0.0, target_ref="target:new"),
        trajectory_id="trajectory:new",
        plan_id="plan:new",
        start_body_state_revision=completed_state.revision,
        duration_s=0.01,
    )

    old_report = controller.activate_trajectory(
        new_trajectory,
        observed_at=NOW + timedelta(milliseconds=50),
        started_monotonic_s=100.02,
    )

    assert old_report == completed_report
    assert old_report.status is BodyMotionExecutionStatus.COMPLETED
    assert controller.execution_report.status is BodyMotionExecutionStatus.PLANNED
    assert authority.current == completed_state

    next_tick = _tick(controller, index=3, monotonic_s=100.04)
    assert next_tick.frame.active_plan_id == "plan:new"
    assert next_tick.frame.active_trajectory_id == "trajectory:new"
    assert next_tick.execution_report.status in {
        BodyMotionExecutionStatus.OBSERVABLE,
        BodyMotionExecutionStatus.COMPLETED,
    }


def test_planned_trajectory_cannot_use_terminal_activation_api() -> None:
    authority, _, controller = _controller()
    new_trajectory = trajectory_for(
        reach_task(extent=0.0, target_ref="target:new"),
        trajectory_id="trajectory:new",
        plan_id="plan:new",
        start_body_state_revision=authority.current.revision,
        duration_s=0.01,
    )

    with pytest.raises(BodySolverError) as error:
        controller.activate_trajectory(
            new_trajectory,
            observed_at=NOW + timedelta(milliseconds=1),
            started_monotonic_s=100.0,
        )

    assert error.value.code is BodySolverFailureCode.INVALID_PLAN
    assert controller.execution_report.status is BodyMotionExecutionStatus.PLANNED
    assert authority.current.revision == 0
