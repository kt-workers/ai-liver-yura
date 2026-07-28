from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.runtime.explicit_activity_executor import ExplicitActivityExecutor


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_execute_runs_action_pipeline_and_records_output() -> None:
    activity = MagicMock(activity_id="activity-1")
    turn_result = MagicMock()
    group = MagicMock(activity_turn_result=turn_result)
    prepared_group = MagicMock(activity_turn_result=turn_result)
    output_result = MagicMock()

    activity_manager = MagicMock()
    action_planner = MagicMock()
    action_planner.plan = AsyncMock(return_value=group)
    action_scheduler = MagicMock()
    action_scheduler.prepare = AsyncMock(return_value=prepared_group)
    action_scheduler.execute = AsyncMock(return_value=output_result)
    agent_life_service = MagicMock()
    trace_logger = MagicMock()

    executor = ExplicitActivityExecutor(
        activity_manager=activity_manager,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        agent_life_service=agent_life_service,
        trace_logger=trace_logger,
    )

    result = await executor.execute(activity)

    assert result is prepared_group
    action_planner.plan.assert_awaited_once_with(activity)
    action_scheduler.prepare.assert_awaited_once_with(group)
    action_scheduler.execute.assert_awaited_once_with(prepared_group)
    activity_manager.record_output_result.assert_called_once_with(
        turn_result,
        output_result,
    )
    activity_manager.complete_processed_activity.assert_called_once_with("activity-1")
    agent_life_service.sync_from_activity_manager.assert_called_once_with()


@pytest.mark.asyncio
async def test_execute_completes_and_syncs_without_output_result() -> None:
    activity = MagicMock(activity_id="activity-2")
    group = MagicMock(activity_turn_result=MagicMock())

    activity_manager = MagicMock()
    action_planner = MagicMock()
    action_planner.plan = AsyncMock(return_value=group)
    action_scheduler = MagicMock()
    action_scheduler.prepare = AsyncMock(return_value=group)
    action_scheduler.execute = AsyncMock(return_value=None)
    agent_life_service = MagicMock()

    executor = ExplicitActivityExecutor(
        activity_manager=activity_manager,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        agent_life_service=agent_life_service,
        trace_logger=MagicMock(),
    )

    assert await executor.execute(activity) is group
    activity_manager.record_output_result.assert_not_called()
    activity_manager.complete_processed_activity.assert_called_once_with("activity-2")
    agent_life_service.sync_from_activity_manager.assert_called_once_with()


@pytest.mark.asyncio
async def test_execute_records_failure_and_reraises_planning_error() -> None:
    activity = MagicMock(activity_id="activity-3")
    error = RuntimeError("planning failed")

    activity_manager = MagicMock()
    action_planner = MagicMock()
    action_planner.plan = AsyncMock(side_effect=error)
    action_scheduler = MagicMock()
    agent_life_service = MagicMock()
    trace_logger = MagicMock()

    executor = ExplicitActivityExecutor(
        activity_manager=activity_manager,
        action_planner=action_planner,
        action_scheduler=action_scheduler,
        agent_life_service=agent_life_service,
        trace_logger=trace_logger,
    )

    with pytest.raises(RuntimeError, match="planning failed"):
        await executor.execute(activity)

    activity_manager.record_turn_result.assert_called_once()
    trace_logger.warning.assert_called_once_with(
        "runtime_coordinator:action_planning:failed",
        activity_id="activity-3",
        failure_stage="action_planning",
        error_type="RuntimeError",
    )
    activity_manager.complete_processed_activity.assert_called_once_with("activity-3")
    agent_life_service.sync_from_activity_manager.assert_called_once_with()
    action_scheduler.prepare.assert_not_called()
    action_scheduler.execute.assert_not_called()
