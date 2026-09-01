from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.body import CanonicalBodyModel
from app.domain.body_realtime.contracts import (
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
    BodySpatialTargetSnapshot,
    BodyStateAuthority,
    ExecutableBodyTrajectory,
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


class CountingTargetResolver:
    def __init__(self, snapshots: tuple[BodySpatialTargetSnapshot, ...]) -> None:
        self._delegate = StaticTargetResolver(snapshots)
        self.resolve_count = 0

    def resolve(self, target_ref: str) -> BodySpatialTargetSnapshot | None:
        self.resolve_count += 1
        return self._delegate.resolve(target_ref)

    def replace(self, snapshot: BodySpatialTargetSnapshot) -> None:
        self._delegate.replace(snapshot)


def _controller(
    resolver: CountingTargetResolver,
    *,
    trajectory: ExecutableBodyTrajectory | None = None,
    initial_angle: float = 0.0,
) -> tuple[CanonicalBodyModel, BodyStateAuthority, BodyContinuousController]:
    model = physical_model()
    authority = BodyStateAuthority(model, physical_state(angle=initial_angle))
    selected = trajectory or trajectory_for(reach_task())
    controller = BodyContinuousController(
        model,
        v2_baseline_body_solver_policy(),
        selected,
        authority,
        resolver,
        started_monotonic_s=100.0,
    )
    return model, authority, controller


def _layer_states() -> tuple[RealtimeLayerState, ...]:
    return tuple(
        RealtimeLayerState(layer, RealtimeLayerStatus.ACTIVE) for layer in RealtimeLayer
    )


def _overlay_bundle(
    revision: int,
    *overlays: ChannelOverlay,
) -> RealtimeOverlayBundle:
    return RealtimeOverlayBundle(
        "overlay-bundle:d10",
        revision,
        None,
        None,
        None,
        NOW,
        16.0,
        0.0,
        tuple(overlays),
        _layer_states(),
    )


def _tick(
    controller: BodyContinuousController,
    *,
    index: int,
    monotonic_s: float,
    supports: tuple[str, ...] = SUPPORT_CONTACT_IDS,
    overlay: RealtimeOverlayBundle | None = None,
) -> BodyControllerTickResult:
    return controller.tick(
        observed_at=NOW + timedelta(milliseconds=16 * index),
        monotonic_now_s=monotonic_s,
        active_support_contact_ids=supports,
        overlay_bundle=overlay,
        frame_id=f"frame:{index}",
        trace_id=f"trace:{index}",
    )


def test_controller_rejects_trajectory_model_revision_mismatch() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.5),))
    trajectory = trajectory_for(reach_task())

    with pytest.raises(BodySolverError) as error:
        _controller(
            resolver,
            trajectory=replace(
                trajectory,
                body_model_revision=trajectory.body_model_revision + 1,
            ),
        )

    assert error.value.code is BodySolverFailureCode.MODEL_REVISION_MISMATCH


def test_controller_rejects_trajectory_model_fingerprint_mismatch() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.5),))
    trajectory = trajectory_for(reach_task())

    with pytest.raises(BodySolverError) as error:
        _controller(
            resolver,
            trajectory=replace(
                trajectory,
                body_model_fingerprint="fingerprint:other",
            ),
        )

    assert error.value.code is BodySolverFailureCode.MODEL_FINGERPRINT_MISMATCH


def test_controller_rejects_solver_policy_revision_mismatch() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.5),))
    trajectory = trajectory_for(reach_task(), solver_policy_revision=2)

    with pytest.raises(BodySolverError) as error:
        _controller(resolver, trajectory=trajectory)

    assert error.value.code is BodySolverFailureCode.INVALID_SOLVER_POLICY


def test_plan_stays_planned_until_validated_frame_is_committed() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.5),))
    _, authority, controller = _controller(resolver)

    assert controller.execution_report.status is BodyMotionExecutionStatus.PLANNED
    assert authority.current.revision == 0

    result = _tick(controller, index=1, monotonic_s=100.0)

    assert result.execution_report.status is BodyMotionExecutionStatus.OBSERVABLE
    assert result.execution_report.started_at == result.frame.observed_at
    assert result.execution_report.observable_at == result.frame.observed_at
    assert authority.current.revision == 1


def test_target_ref_is_snapshotted_once_for_phase_not_re_resolved_each_tick() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.6, generation=1),))
    _, _, controller = _controller(resolver)

    _tick(controller, index=1, monotonic_s=100.0)
    resolver.replace(position_snapshot(-0.6, generation=2))
    _tick(controller, index=2, monotonic_s=100.0 + 1.0 / 60.0)

    assert resolver.resolve_count == 1


def test_failed_tick_does_not_commit_or_advance_control_time() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.6),))
    _, authority, controller = _controller(resolver)

    with pytest.raises(BodySolverError) as error:
        _tick(
            controller,
            index=1,
            monotonic_s=100.0,
            supports=SUPPORT_CONTACT_IDS[:2],
        )
    assert error.value.code is BodySolverFailureCode.INSUFFICIENT_SUPPORT_GEOMETRY
    assert authority.current.revision == 0
    assert controller.execution_report.status is BodyMotionExecutionStatus.PLANNED

    retry = _tick(controller, index=1, monotonic_s=100.0)
    assert retry.frame.body_state_revision == 1


def test_controller_starts_from_current_pose_without_home_reset() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.8),))
    _, authority, controller = _controller(resolver, initial_angle=0.4)

    _tick(controller, index=1, monotonic_s=100.0)

    coordinate = authority.current.joint_dof_states[0].coordinates[0]
    assert coordinate.position_radians > 0.39
    assert coordinate.position_radians <= 0.4 + 1.5 / 60.0


def test_overlay_conflict_is_deterministic_and_stale_bundle_degrades() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.5),))
    _, authority, controller = _controller(resolver)
    high = ChannelOverlay(
        "overlay:high",
        RealtimeLayer.GAZE,
        RealtimeChannel.GAZE_X,
        0.75,
        1.0,
        90,
    )
    low = ChannelOverlay(
        "overlay:low",
        RealtimeLayer.GAZE,
        RealtimeChannel.GAZE_X,
        -0.5,
        1.0,
        10,
    )

    applied = _tick(
        controller,
        index=1,
        monotonic_s=100.0,
        overlay=_overlay_bundle(authority.current.revision, low, high),
    )
    assert applied.frame.channel_values[0].channel is RealtimeChannel.GAZE_X
    assert applied.frame.channel_values[0].value == pytest.approx(0.75)
    assert applied.frame.applied_overlay_refs == ("overlay:high",)
    assert applied.frame.degraded_overlay_refs == ("overlay:low",)
    coordinate = authority.current.joint_dof_states[0].coordinates[0]
    assert -1.2 <= coordinate.position_radians <= 1.2

    stale = _tick(
        controller,
        index=2,
        monotonic_s=100.0 + 1.0 / 60.0,
        overlay=_overlay_bundle(0, high, low),
    )
    assert stale.frame.channel_values == ()
    assert stale.frame.applied_overlay_refs == ()
    assert stale.frame.degraded_overlay_refs == ("overlay:high", "overlay:low")


def test_controller_continues_last_phase_after_nominal_end_until_completion() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.8),))
    trajectory = trajectory_for(reach_task(), duration_s=0.01)
    _, authority, controller = _controller(resolver, trajectory=trajectory)

    first = _tick(controller, index=1, monotonic_s=100.0)
    after_end = _tick(controller, index=2, monotonic_s=100.02)

    assert first.execution_report.status is BodyMotionExecutionStatus.OBSERVABLE
    assert after_end.execution_report.status is BodyMotionExecutionStatus.OBSERVABLE
    assert after_end.frame.active_trajectory_id == trajectory.trajectory_id
    assert authority.current.revision == 2


def test_interrupt_terminal_blocks_additional_frame_commit() -> None:
    resolver = CountingTargetResolver((position_snapshot(0.5),))
    _, authority, controller = _controller(resolver)
    _tick(controller, index=1, monotonic_s=100.0)
    revision = authority.current.revision

    report = controller.interrupt(NOW + timedelta(milliseconds=17))

    assert report.status is BodyMotionExecutionStatus.INTERRUPTED
    assert report.completed_at == NOW + timedelta(milliseconds=17)
    with pytest.raises(BodySolverError) as error:
        _tick(controller, index=2, monotonic_s=100.0 + 1.0 / 60.0)
    assert error.value.code is BodySolverFailureCode.INVALID_PLAN
    assert authority.current.revision == revision


def test_supersede_preserves_committed_dynamic_state_and_bounds_transition() -> None:
    resolver = CountingTargetResolver(
        (
            position_snapshot(0.8, target_ref="target:old"),
            position_snapshot(-0.8, target_ref="target:new"),
        )
    )
    old_trajectory = trajectory_for(
        reach_task(target_ref="target:old"),
        trajectory_id="trajectory:old",
        plan_id="plan:old",
        duration_s=1.0,
    )
    model, authority, controller = _controller(resolver, trajectory=old_trajectory)
    dt = 1.0 / 60.0
    _tick(controller, index=1, monotonic_s=100.0)
    _tick(controller, index=2, monotonic_s=100.0 + dt)
    before_state = authority.current
    before = before_state.joint_dof_states[0].coordinates[0]
    new_trajectory = trajectory_for(
        reach_task(target_ref="target:new"),
        trajectory_id="trajectory:new",
        plan_id="plan:new",
        start_body_state_revision=before_state.revision,
        duration_s=1.0,
    )

    old_report = controller.supersede_trajectory(
        new_trajectory,
        observed_at=NOW + timedelta(milliseconds=33),
        started_monotonic_s=100.0 + dt,
    )

    assert old_report.status is BodyMotionExecutionStatus.SUPERSEDED
    assert old_report.completed_at == NOW + timedelta(milliseconds=33)
    assert controller.execution_report.status is BodyMotionExecutionStatus.PLANNED
    assert authority.current == before_state

    next_result = _tick(controller, index=3, monotonic_s=100.0 + 2.0 * dt)
    after = authority.current.joint_dof_states[0].coordinates[0]
    dynamic = next(item for item in model.joints if item.joint_id == "arm").dynamic_limits[0]

    assert next_result.frame.active_plan_id == "plan:new"
    assert next_result.frame.active_trajectory_id == "trajectory:new"
    assert abs(after.position_radians - before.position_radians) <= (
        dynamic.max_velocity_radians_per_second * dt + 1e-12
    )
    assert abs(
        after.velocity_radians_per_second - before.velocity_radians_per_second
    ) <= dynamic.max_acceleration_radians_per_second2 * dt + 1e-12
    assert abs(
        after.acceleration_radians_per_second2
        - before.acceleration_radians_per_second2
    ) <= dynamic.max_jerk_radians_per_second3 * dt + 1e-12
