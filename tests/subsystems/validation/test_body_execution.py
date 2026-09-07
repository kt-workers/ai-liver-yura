"""実際の身体計画・姿勢更新の接続と計画待機中の継続を確認する。"""

import asyncio
from dataclasses import replace

import pytest

from app.adapters.llm.production import UnavailableLLMRolePort
from app.domain.body_motion_planning.planner import descriptor
from app.domain.body_solver import BodyStateAuthority, v2_baseline_body_solver_policy
from app.subsystems.validation.body_execution import BodyExecutionLabCase, body_execution_target
from app.subsystems.validation.contracts import DelayInjection, LabMode, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.body_integration import test_runtime as body
from tests.domain.body_motion_planning.test_contracts import _policy
from tests.domain.body_solver.d10_fixtures import (
    SUPPORT_CONTACT_IDS,
    physical_model,
    physical_state,
    position_snapshot,
    reach_task,
    trajectory_for,
)
from tests.subsystems.validation.json_values import array_at, integer_at, value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def setup() -> tuple[BodyExecutionLabCase, ValidationRunner]:
    model = physical_model()
    state = physical_state()
    solver_policy = v2_baseline_body_solver_policy()
    submission = body._submission(
        BodyStateAuthority(model, state), index=1, target_ref="target:new"
    )
    case = BodyExecutionLabCase(
        FIXTURE,
        model,
        state,
        trajectory_for(
            reach_task(target_ref="target:initial"),
            plan_id="plan:initial",
            trajectory_id="trajectory:initial",
            solver_policy_revision=solver_policy.policy_revision,
            duration_s=30.0,
        ),
        solver_policy,
        _policy(),
        submission,
        (
            position_snapshot(0.35, target_ref="target:initial"),
            position_snapshot(0.8, target_ref="target:new"),
        ),
        SUPPORT_CONTACT_IDS,
        submission.created_at,
        6,
        0.01,
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    return case, runner_for(case)


def runner_for(case: BodyExecutionLabCase, *, timeout: float = 1.0) -> ValidationRunner:
    return ValidationRunner(
        (
            body_execution_target(
                (case,),
                UnavailableLLMRolePort((descriptor(case.planning_policy),)),
                PROVENANCE,
                "1",
                (),
            ),
        ),
        replace(POLICY, max_intervals=100, max_export_bytes=2_000_000, timeout_seconds=timeout),
    )


@pytest.mark.asyncio
async def test_plan_reaches_actual_controller_and_latest_frame_without_renderer() -> None:
    case, runner = setup()
    result = await runner.run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT, repeat_count=2),
        case.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    assert len(result.stage_results) == 2
    for stage in result.stage_results:
        output = stage.typed_outputs
        assert integer_at(output, "final_state", "revision") == case.initial_state.revision + 6
        assert value_at(output, "session_before_close", "active_plan_id") == case.submission.plan_id
        assert integer_at(output, "publication", "coalesced_frames") == 5
        assert integer_at(output, "pending_task_count_after_close") == 0
        assert value_at(output, "publication", "frame", "body_state_revision") == value_at(
            output, "final_state", "revision"
        )
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_slow_planning_keeps_pose_advancing_and_close_collects_planning() -> None:
    case, runner = setup()
    result = await runner.run(
        replace(
            spec(),
            target_module="body_execution",
            mode=LabMode.ADJACENT,
            delay_injections=(DelayInjection("body.execution.planning", 20.0, 1),),
        ),
        case.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    ticks = array_at(output, "ticks")
    assert len(ticks) == 6
    for index, tick in enumerate(ticks):
        assert value_at(tick, "session", "status") == "planning"
        assert integer_at(tick, "result", "frame", "body_state_revision") == (
            case.initial_state.revision + index + 1
        )
        assert integer_at(tick, "pending_task_count") == 1
    assert value_at(output, "session_after_close", "status") == "cancelled"
    assert integer_at(output, "pending_task_count_after_close") == 0
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_timeout_cancels_owned_body_planning_task() -> None:
    case, _ = setup()
    case = replace(case, tick_count=100)
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    runner = runner_for(case, timeout=0.03)
    result = await runner.run(
        replace(
            spec(),
            target_module="body_execution",
            mode=LabMode.ADJACENT,
            delay_injections=(DelayInjection("body.execution.planning", 20.0, 1),),
        ),
        case.fixture,
    )
    assert result.status is RunStatus.TIMED_OUT
    assert runner.pending_count == 0
    assert not [
        task for task in asyncio.all_tasks() if task.get_name().startswith("body-planning:")
    ]


@pytest.mark.asyncio
async def test_changed_physical_input_is_not_silently_substituted() -> None:
    case, runner = setup()
    result = await runner.run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT),
        replace(case.fixture, typed_inputs={"tick_count": 1}),
    )
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert not [item for item in result.timeline if item.stage.startswith("body.")]


@pytest.mark.asyncio
async def test_unavailable_motion_llm_keeps_existing_physical_execution() -> None:
    case, _ = setup()
    case = replace(
        case,
        submission=replace(
            case.submission,
            snapshot=replace(case.submission.snapshot, deterministic_directive=None),
        ),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case).run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT), case.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "session_before_close", "status") == "failed"
    assert value_at(output, "session_before_close", "active_plan_id") is None
    assert integer_at(output, "final_state", "revision") == case.initial_state.revision + 6
    assert integer_at(output, "pending_task_count_after_close") == 0


@pytest.mark.asyncio
async def test_delayed_plan_is_adopted_after_pose_revision_has_advanced() -> None:
    case, runner = setup()
    result = await runner.run(
        replace(
            spec(),
            target_module="body_execution",
            mode=LabMode.ADJACENT,
            delay_injections=(DelayInjection("body.execution.planning", 0.02, 1),),
        ),
        case.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "ticks", 0, "session", "status") == "planning"
    assert value_at(output, "session_before_close", "active_plan_id") == case.submission.plan_id
    assert integer_at(output, "final_state", "revision") > case.initial_state.revision
    plan_interval = next(
        item for item in result.timeline if item.stage == "body.execution.planning"
    )
    tick_intervals = [item for item in result.timeline if item.stage == "body.execution.tick"]
    assert any(
        plan_interval.started_ns < item.started_ns < plan_interval.completed_ns
        for item in tick_intervals
    )


@pytest.mark.asyncio
async def test_realtime_layers_reach_pose_during_pending_planning() -> None:
    from app.subsystems.validation.body_execution import BodyRealtimeLabSettings

    case, _ = setup()
    case = replace(case, realtime=BodyRealtimeLabSettings(13, 0.002))
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case).run(
        replace(
            spec(),
            target_module="body_execution",
            mode=LabMode.ADJACENT,
            delay_injections=(DelayInjection("body.execution.planning", 20.0, 1),),
        ),
        case.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    ticks = array_at(output, "ticks")
    assert integer_at(output, "realtime", "overlay_count") > 1
    applied = []
    for tick in ticks:
        assert value_at(tick, "session", "status") == "planning"
        refs = array_at(tick, "result", "frame", "applied_overlay_refs")
        if refs:
            applied.append(tick)
            overlay_ids = {
                value_at(item, "overlay_id")
                for item in array_at(tick, "latest_overlay", "channel_overlays")
            }
            assert set(refs) <= overlay_ids
    assert len(applied) >= 2
    assert integer_at(output, "realtime", "pending_task_count_after_close") == 0
    assert integer_at(output, "pending_task_count_after_close") == 0
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "body-realtime"]


@pytest.mark.asyncio
async def test_timeout_collects_both_realtime_and_planning_tasks() -> None:
    from app.subsystems.validation.body_execution import BodyRealtimeLabSettings

    case, _ = setup()
    case = replace(case, tick_count=100, realtime=BodyRealtimeLabSettings(13, 0.002))
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case, timeout=0.03).run(
        replace(
            spec(),
            target_module="body_execution",
            mode=LabMode.ADJACENT,
            delay_injections=(DelayInjection("body.execution.planning", 20.0, 1),),
        ),
        case.fixture,
    )
    assert result.status is RunStatus.TIMED_OUT
    assert not [
        task
        for task in asyncio.all_tasks()
        if (task.get_name() == "body-realtime" or task.get_name().startswith("body-planning:"))
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("delay_s", [5.0, 20.0])
async def test_real_elapsed_planning_delay_keeps_realtime_and_pose_running(delay_s: float) -> None:
    from app.subsystems.validation.body_execution import BodyRealtimeLabSettings

    case, _ = setup()
    case = replace(
        case,
        tick_count=int(delay_s * 10) + 5,
        tick_interval_s=0.1,
        realtime=BodyRealtimeLabSettings(13, 0.01),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    runner = ValidationRunner(
        (
            body_execution_target(
                (case,),
                UnavailableLLMRolePort((descriptor(case.planning_policy),)),
                PROVENANCE,
                "1",
                (),
            ),
        ),
        replace(
            POLICY,
            max_intervals=case.tick_count + 10,
            max_export_bytes=50_000_000,
            timeout_seconds=delay_s + 5,
        ),
    )
    result = await runner.run(
        replace(
            spec(),
            target_module="body_execution",
            mode=LabMode.ADJACENT,
            delay_injections=(DelayInjection("body.execution.planning", delay_s, 1),),
        ),
        case.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    plan_interval = next(
        item for item in result.timeline if item.stage == "body.execution.planning"
    )
    assert (plan_interval.completed_ns - plan_interval.started_ns) / 1e9 >= delay_s
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "session_before_close", "active_plan_id") == case.submission.plan_id
    assert integer_at(output, "final_state", "revision") == (
        case.initial_state.revision + case.tick_count
    )
    pending_ticks = [
        item
        for item in array_at(output, "ticks")
        if value_at(item, "session", "status") == "planning"
    ]
    assert len(pending_ticks) >= int(delay_s * 5)
    assert integer_at(pending_ticks[-1], "overlay_count") > integer_at(
        pending_ticks[0], "overlay_count"
    )
    assert sum(
        bool(array_at(item, "result", "frame", "applied_overlay_refs")) for item in pending_ticks
    ) >= int(delay_s * 5)
    assert integer_at(output, "pending_task_count_after_close") == 0
