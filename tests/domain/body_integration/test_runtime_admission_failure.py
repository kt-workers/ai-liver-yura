import asyncio
from dataclasses import replace

import pytest

from app.domain.body_motion_planning import (
    BodyMotionPlanAuthority,
    DeterministicBodyMotionPlanner,
)
from app.domain.body_solver import BodyStateAuthority
from tests.domain.body_integration.test_runtime import (
    _at,
    _ControlledPlanner,
    _LivePlanningState,
    _runtime,
    _submission,
)
from tests.domain.body_solver.d10_fixtures import (
    SUPPORT_CONTACT_IDS,
    physical_model,
    physical_state,
)


@pytest.mark.asyncio
async def test_rejected_trajectory_admission_does_not_stop_current_physical_tick() -> None:
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

    first = runtime.tick_physical(
        observed_at=_at(0.1),
        monotonic_now_s=0.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:before-rejected-admission",
        trace_id="trace:before-rejected-admission",
    )
    assert first.frame.active_plan_id == "plan:initial"

    duplicate_trajectory = replace(
        _submission(authority, index=1, target_ref="target:new"),
        trajectory_id="trajectory:initial",
    )
    runtime.submit_planning(duplicate_trajectory, supersede_allowed=True)
    gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    result = runtime.tick_physical(
        observed_at=_at(1.1),
        monotonic_now_s=1.1,
        active_support_contact_ids=SUPPORT_CONTACT_IDS,
        frame_id="frame:after-rejected-admission",
        trace_id="trace:after-rejected-admission",
    )

    assert result.frame.active_plan_id == "plan:initial"
    assert result.frame.body_state_revision == first.frame.body_state_revision + 1
    session = runtime.session("session:1")
    assert session is not None
    assert session.status.value == "rejected"
    assert session.terminal_reason == "trajectory_admission_rejected:invalid_plan"
