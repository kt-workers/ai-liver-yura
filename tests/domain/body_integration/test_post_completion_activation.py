from __future__ import annotations

import asyncio

import pytest

from app.domain.body_integration import BodyExecutionSessionStatus
from app.domain.body_motion_planning import (
    BodyMotionPlanAuthority,
    DeterministicBodyMotionPlanner,
)
from app.domain.body_solver import BodyMotionExecutionStatus, BodyStateAuthority
from tests.domain.body_integration.test_runtime import (
    _at,
    _ControlledPlanner,
    _LivePlanningState,
    _overlay,
    _runtime,
    _submission,
)
from tests.domain.body_solver.d10_fixtures import (
    SUPPORT_CONTACT_IDS,
    physical_model,
    physical_state,
)


@pytest.mark.asyncio
async def test_completed_session_keeps_baseline_then_activates_next_plan_on_same_controller(
) -> None:
    first_gate = asyncio.Event()
    second_gate = asyncio.Event()
    first_gate.set()
    seed_authority = BodyStateAuthority(physical_model(), physical_state())
    planner = _ControlledPlanner(
        DeterministicBodyMotionPlanner(
            _LivePlanningState(seed_authority),
            BodyMotionPlanAuthority(),
        ),
        {"request:1": first_gate, "request:2": second_gate},
    )
    runtime, authority, _ = _runtime(planner)
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
    await asyncio.sleep(0)

    first = runtime.tick_physical(
        observed_at=_at(0.1),
        monotonic_now_s=0.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:initial-before-first-plan",
        trace_id="trace:first",
    )
    assert first.frame.active_plan_id == "plan:initial"
    first_session = runtime.session("session:1")
    assert first_session is not None
    assert first_session.status is BodyExecutionSessionStatus.PLAN_READY

    monotonic = 0.1
    for index in range(1, 241):
        monotonic += 1.0 / 60.0
        runtime.tick_physical(
            observed_at=_at(monotonic),
            monotonic_now_s=monotonic,
            active_support_contact_ids=SUPPORT_CONTACT_IDS,
            frame_id=f"frame:first:{index}",
            trace_id="trace:first",
        )
        first_session = runtime.session("session:1")
        assert first_session is not None
        if first_session.status is BodyExecutionSessionStatus.COMPLETED:
            break
    else:
        pytest.fail("first Body session did not complete within bounded ticks")

    assert runtime.controller.execution_report.status is BodyMotionExecutionStatus.COMPLETED
    first_completed = runtime.session("session:1")
    assert first_completed is not None
    assert first_completed.status is BodyExecutionSessionStatus.COMPLETED
    assert first_completed.completed_at is not None
    completed_at = first_completed.completed_at
    completed_revision = authority.current.revision

    runtime.submit_planning(
        _submission(authority, index=2, target_ref="target:late"),
        supersede_allowed=True,
    )
    await asyncio.sleep(0)
    runtime.publish_overlay(_overlay(authority.current.revision))

    monotonic += 1.0 / 60.0
    baseline = runtime.tick_physical(
        observed_at=_at(monotonic),
        monotonic_now_s=monotonic,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:completed-baseline",
        trace_id="trace:baseline",
    )

    assert id(runtime.controller) == controller_identity
    assert baseline.phase_id == "baseline:continuation"
    assert baseline.frame.active_plan_id is None
    assert baseline.frame.active_trajectory_id is None
    assert baseline.frame.body_state_revision == completed_revision + 1
    assert baseline.frame.applied_overlay_refs == ("overlay:gaze-x",)
    old_session_during_wait = runtime.session("session:1")
    assert old_session_during_wait is not None
    assert old_session_during_wait.status is BodyExecutionSessionStatus.COMPLETED
    assert old_session_during_wait.completed_at == completed_at
    pending = runtime.session("session:2")
    assert pending is not None
    assert pending.status is BodyExecutionSessionStatus.PLANNING

    second_gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    monotonic += 1.0 / 60.0
    activated = runtime.tick_physical(
        observed_at=_at(monotonic),
        monotonic_now_s=monotonic,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:second-activated",
        trace_id="trace:second",
    )

    assert id(runtime.controller) == controller_identity
    assert activated.frame.active_plan_id == "plan:2"
    assert activated.frame.active_trajectory_id == "trajectory:2"
    old_session_after_activation = runtime.session("session:1")
    assert old_session_after_activation is not None
    assert old_session_after_activation.status is BodyExecutionSessionStatus.COMPLETED
    assert old_session_after_activation.completed_at == completed_at
    second = runtime.session("session:2")
    assert second is not None
    assert second.status is BodyExecutionSessionStatus.EXECUTING
    assert second.started_at is not None
