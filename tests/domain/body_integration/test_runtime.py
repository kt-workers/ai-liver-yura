from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.body import AnatomicalRegion, AnatomicalSide
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionContext,
    BodyFocusExpressionConstraint,
    NormalizedExpressionValue,
)
from app.domain.body_integration import (
    BodyExecutionSessionStatus,
    BodyIntegrationRuntime,
    BodyPlanningSubmission,
)
from app.domain.body_motion_planning import (
    BodyBalanceMode,
    BodyMotionEffect,
    BodyMotionGoal,
    BodyMotionIntentView,
    BodyMotionPhase,
    BodyMotionPlan,
    BodyMotionPlanAuthority,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    BodyMotionSelector,
    BodySpatialTarget,
    BodySpatialTargetKind,
    DeterministicBodyMotionPlanner,
    DeterministicBodyPlanningDirective,
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
    BodyStateAuthority,
    LatestBodyFrameBuffer,
    v2_baseline_body_solver_policy,
)
from app.domain.contracts import RevisionVector
from app.domain.executive import ExecutiveInterruptibility, ExecutivePriority
from tests.domain.body_solver.d10_fixtures import (
    SUPPORT_CONTACT_IDS,
    StaticTargetResolver,
    physical_model,
    physical_state,
    position_snapshot,
    reach_task,
    trajectory_for,
)

NOW = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def _expression(*, revision: int = 1) -> BodyExpressionContext:
    return BodyExpressionContext(
        revision,
        1,
        1,
        1,
        1,
        1,
        "generic",
        1,
        1,
        "policy",
        1,
        tuple(
            BodyExpressionAxisValue(axis, NormalizedExpressionValue(0.0))
            for axis in BodyExpressionAxis
        ),
        BodyFocusExpressionConstraint(None, None, (), None, None),
        (),
        (),
        (),
        NOW,
    )


def _intent(*, index: int, target_ref: str) -> BodyMotionIntentView:
    return BodyMotionIntentView(
        f"decision:{index}",
        f"intent:{index}",
        "対象へ右腕を向ける",
        f"motion:reach:{index}",
        target_ref,
        (),
        (f"event:{index}",),
        RevisionVector(index, index, index),
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (),
        (),
    )


def _directive(*, target_ref: str, goal_id: str) -> DeterministicBodyPlanningDirective:
    goal = BodyMotionGoal(
        goal_id,
        BodyMotionEffect.TRANSLATE,
        BodyMotionSelector(
            AnatomicalRegion.ARM,
            AnatomicalSide.RIGHT,
            ("chain:arm",),
            ("arm",),
        ),
        BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, target_ref, 1.0),
        1.0,
        (),
    )
    return DeterministicBodyPlanningDirective(
        (goal,),
        (
            BodyMotionPhase(
                f"phase:{goal_id}",
                (goal_id,),
                1.0,
                BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
            ),
        ),
        (),
        (),
    )


def _snapshot(
    authority: BodyStateAuthority,
    *,
    index: int,
    target_ref: str,
) -> BodyMotionPlanningContextSnapshot:
    return BodyMotionPlanningContextSnapshot(
        f"request:{index}",
        _intent(index=index, target_ref=target_ref),
        physical_model(),
        authority.current,
        _expression(revision=index),
        (),
        (),
        _at(float(index)),
        f"trace:{index}",
        _directive(target_ref=target_ref, goal_id=f"goal:{index}"),
    )


class _LivePlanningState:
    def __init__(self, authority: BodyStateAuthority) -> None:
        self._authority = authority

    async def current_commit_state(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
    ) -> BodyMotionPlanningCommitState:
        return BodyMotionPlanningCommitState(
            snapshot.intent.revisions,
            snapshot.intent,
            snapshot.body_model,
            self._authority.current,
            snapshot.expression,
            snapshot.constraints,
            snapshot.capabilities,
            snapshot.intent.preconditions,
            self._authority.current.observed_at,
        )


class _ControlledPlanner:
    def __init__(
        self,
        inner: DeterministicBodyMotionPlanner,
        gates: dict[str, asyncio.Event],
        *,
        ignore_cancel_requests: frozenset[str] = frozenset(),
    ) -> None:
        self._inner = inner
        self._gates = gates
        self._ignore_cancel_requests = ignore_cancel_requests

    async def plan(
        self,
        snapshot: BodyMotionPlanningContextSnapshot,
        *,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> BodyMotionPlan:
        gate = self._gates[snapshot.request_id]
        try:
            await gate.wait()
        except asyncio.CancelledError:
            if snapshot.request_id not in self._ignore_cancel_requests:
                raise
            await gate.wait()
        return await self._inner.plan(
            snapshot,
            candidate_id=candidate_id,
            plan_id=plan_id,
            created_at=created_at,
        )


def _runtime(
    planner: _ControlledPlanner,
) -> tuple[BodyIntegrationRuntime, BodyStateAuthority, LatestBodyFrameBuffer]:
    model = physical_model()
    policy = v2_baseline_body_solver_policy()
    authority = BodyStateAuthority(model, physical_state())
    resolver = StaticTargetResolver(
        (
            position_snapshot(0.35, target_ref="target:initial"),
            position_snapshot(0.8, target_ref="target:new"),
            position_snapshot(-0.5, target_ref="target:late"),
        )
    )
    initial = trajectory_for(
        reach_task(target_ref="target:initial"),
        plan_id="plan:initial",
        trajectory_id="trajectory:initial",
        solver_policy_revision=policy.policy_revision,
        duration_s=30.0,
    )
    controller = BodyContinuousController(
        model,
        policy,
        initial,
        authority,
        resolver,
        started_monotonic_s=0.0,
    )
    frame_buffer = LatestBodyFrameBuffer(model.body_model_id)
    return (
        BodyIntegrationRuntime(
            model,
            policy,
            authority,
            controller,
            planner,
            frame_buffer,
        ),
        authority,
        frame_buffer,
    )


def _submission(
    authority: BodyStateAuthority,
    *,
    index: int,
    target_ref: str,
) -> BodyPlanningSubmission:
    return BodyPlanningSubmission(
        f"session:{index}",
        f"command:{index}",
        _snapshot(authority, index=index, target_ref=target_ref),
        f"candidate:{index}",
        f"plan:{index}",
        f"trajectory:{index}",
        2.0,
        _at(float(index)),
    )


def _overlay(revision: int) -> RealtimeOverlayBundle:
    return RealtimeOverlayBundle(
        "overlay-bundle:test",
        revision,
        None,
        None,
        None,
        _at(0.05),
        16.0,
        0.0,
        (
            ChannelOverlay(
                "overlay:gaze-x",
                RealtimeLayer.GAZE,
                RealtimeChannel.GAZE_X,
                0.25,
                1.0,
                100,
            ),
        ),
        tuple(
            RealtimeLayerState(
                layer,
                (
                    RealtimeLayerStatus.ACTIVE
                    if layer is RealtimeLayer.GAZE
                    else RealtimeLayerStatus.INACTIVE_NO_SOURCE
                ),
            )
            for layer in RealtimeLayer
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("planner_delay_seconds", (5.0, 20.0))
async def test_planner_delay_does_not_stop_current_physical_frames(
    planner_delay_seconds: float,
) -> None:
    gate = asyncio.Event()
    seed_authority = BodyStateAuthority(physical_model(), physical_state())
    inner = DeterministicBodyMotionPlanner(
        _LivePlanningState(seed_authority),
        BodyMotionPlanAuthority(),
    )
    planner = _ControlledPlanner(inner, {"request:1": gate})
    runtime, authority, frame_buffer = _runtime(planner)
    # plannerが参照するlive stateもruntimeのAuthorityへbindする。
    planner._inner = DeterministicBodyMotionPlanner(
        _LivePlanningState(authority),
        BodyMotionPlanAuthority(),
    )
    controller_identity = id(runtime.controller)

    runtime.submit_planning(
        _submission(authority, index=1, target_ref="target:new"),
        supersede_allowed=True,
    )
    await asyncio.sleep(0)

    for index, monotonic in enumerate(
        (0.1, planner_delay_seconds / 2, planner_delay_seconds),
        start=1,
    ):
        result = runtime.tick_physical(
            observed_at=_at(monotonic),
            monotonic_now_s=monotonic,
            active_support_contact_ids=SUPPORT_CONTACT_IDS,
            frame_id=f"frame:pending:{index}",
            trace_id="trace:current",
        )
        assert result.frame.active_plan_id == "plan:initial"

    pending = runtime.session("session:1")
    assert pending is not None
    assert pending.status is BodyExecutionSessionStatus.PLANNING
    assert authority.current.revision == 3

    gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    activated = runtime.tick_physical(
        observed_at=_at(planner_delay_seconds + 0.1),
        monotonic_now_s=planner_delay_seconds + 0.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:new",
        trace_id="trace:new",
    )

    assert id(runtime.controller) == controller_identity
    assert activated.frame.active_plan_id == "plan:1"
    session = runtime.session("session:1")
    assert session is not None
    assert session.status is BodyExecutionSessionStatus.EXECUTING
    assert session.started_at is not None
    take = frame_buffer.take_latest()
    assert take.frame == activated.frame
    assert take.coalesced_frames >= 3


@pytest.mark.asyncio
async def test_realtime_overlay_remains_independent_while_planner_is_pending() -> None:
    gate = asyncio.Event()
    seed_authority = BodyStateAuthority(physical_model(), physical_state())
    planner = _ControlledPlanner(
        DeterministicBodyMotionPlanner(
            _LivePlanningState(seed_authority),
            BodyMotionPlanAuthority(),
        ),
        {"request:1": gate},
    )
    runtime, authority, _ = _runtime(planner)
    planner._inner = DeterministicBodyMotionPlanner(
        _LivePlanningState(authority),
        BodyMotionPlanAuthority(),
    )
    runtime.submit_planning(
        _submission(authority, index=1, target_ref="target:new"),
        supersede_allowed=True,
    )
    await asyncio.sleep(0)

    runtime.publish_overlay(_overlay(authority.current.revision))
    result = runtime.tick_physical(
        observed_at=_at(0.1),
        monotonic_now_s=0.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:overlay",
        trace_id="trace:overlay",
    )

    assert result.frame.active_plan_id == "plan:initial"
    assert any(
        item.channel is RealtimeChannel.GAZE_X and item.value == pytest.approx(0.25)
        for item in result.frame.channel_values
    )
    assert result.frame.applied_overlay_refs == ("overlay:gaze-x",)
    session = runtime.session("session:1")
    assert session is not None
    assert session.status is BodyExecutionSessionStatus.PLANNING


@pytest.mark.asyncio
async def test_superseded_late_planner_result_is_never_admitted_to_controller() -> None:
    old_gate = asyncio.Event()
    new_gate = asyncio.Event()
    seed_authority = BodyStateAuthority(physical_model(), physical_state())
    planner = _ControlledPlanner(
        DeterministicBodyMotionPlanner(
            _LivePlanningState(seed_authority),
            BodyMotionPlanAuthority(),
        ),
        {"request:1": old_gate, "request:2": new_gate},
        ignore_cancel_requests=frozenset({"request:1"}),
    )
    runtime, authority, _ = _runtime(planner)
    planner._inner = DeterministicBodyMotionPlanner(
        _LivePlanningState(authority),
        BodyMotionPlanAuthority(),
    )

    runtime.tick_physical(
        observed_at=_at(0.1),
        monotonic_now_s=0.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:initial",
        trace_id="trace:initial",
    )
    runtime.submit_planning(
        _submission(authority, index=1, target_ref="target:late"),
        supersede_allowed=True,
    )
    await asyncio.sleep(0)
    runtime.submit_planning(
        _submission(authority, index=2, target_ref="target:new"),
        supersede_allowed=True,
    )

    old_session = runtime.session("session:1")
    assert old_session is not None
    assert old_session.status is BodyExecutionSessionStatus.SUPERSEDED

    old_gate.set()
    new_gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    result = runtime.tick_physical(
        observed_at=_at(2.1),
        monotonic_now_s=2.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:newest",
        trace_id="trace:newest",
    )

    assert result.frame.active_plan_id == "plan:2"
    assert result.frame.active_plan_id != "plan:1"
    active = runtime.active_session
    assert active is not None
    assert active.session_id == "session:2"
    assert active.status is BodyExecutionSessionStatus.EXECUTING


@pytest.mark.asyncio
async def test_shutdown_cancels_owned_planning_without_resetting_body_state() -> None:
    gate = asyncio.Event()
    seed_authority = BodyStateAuthority(physical_model(), physical_state())
    planner = _ControlledPlanner(
        DeterministicBodyMotionPlanner(
            _LivePlanningState(seed_authority),
            BodyMotionPlanAuthority(),
        ),
        {"request:1": gate},
    )
    runtime, authority, _ = _runtime(planner)
    planner._inner = DeterministicBodyMotionPlanner(
        _LivePlanningState(authority),
        BodyMotionPlanAuthority(),
    )
    runtime.submit_planning(
        _submission(authority, index=1, target_ref="target:new"),
        supersede_allowed=True,
    )
    await asyncio.sleep(0)
    runtime.tick_physical(
        observed_at=_at(0.1),
        monotonic_now_s=0.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:before-close",
        trace_id="trace:before-close",
    )
    pose_before_close = authority.current.pose
    revision_before_close = authority.current.revision

    await runtime.close(observed_at=_at(0.2))

    assert runtime.pending_task_count == 0
    assert authority.current.revision == revision_before_close
    assert authority.current.pose == pose_before_close
    session = runtime.session("session:1")
    assert session is not None
    assert session.status is BodyExecutionSessionStatus.CANCELLED
