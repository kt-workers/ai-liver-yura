from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from app.domain.actions import ActionPlanGroup
from app.domain.activities import Activity, ActivityType
from app.domain.activity_turn_result import (
    ActivityOutputResult,
    ActivityOutputStatus,
    ActivityTurnResult,
)
from app.domain.events import AgentEventType
from app.runtime.explicit_activity_executor import ExplicitActivityExecutor


pytestmark = pytest.mark.unit


def _activity(activity_id: str) -> Activity:
    return Activity(
        activity_type=ActivityType.DIRECTED_TALK,
        goal="指示された内容を話す",
        activity_id=activity_id,
    )


def _turn_result(activity_id: str) -> ActivityTurnResult:
    return ActivityTurnResult(
        activity_turn_id=f"turn-{activity_id}",
        activity_type=ActivityType.DIRECTED_TALK.value,
    )


@pytest.mark.asyncio
async def test_execute_runs_action_pipeline_and_records_output() -> None:
    activity = _activity("activity-1")
    turn_result = _turn_result(activity.activity_id)
    group = ActionPlanGroup(
        source_activity_id=activity.activity_id,
        activity_turn_result=turn_result,
    )
    prepared_group = group
    output_result = ActivityOutputResult(
        status=ActivityOutputStatus.COMPLETED,
        output_unit_id=group.group_id,
        activity_turn_id=turn_result.activity_turn_id,
    )

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
    activity_manager.complete_processed_activity.assert_called_once_with(
        "activity-1",
        result=ANY,
    )
    result_event = agent_life_service.handle_event.call_args.args[0]
    assert result_event.event_type == AgentEventType.ACTIVITY_RESULT_RECORDED
    assert result_event.payload["outcome"] == "completed"


@pytest.mark.asyncio
async def test_execute_completes_and_records_no_action_result() -> None:
    activity = _activity("activity-2")
    group = ActionPlanGroup(
        source_activity_id=activity.activity_id,
        activity_turn_result=_turn_result(activity.activity_id),
    )

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
    activity_manager.complete_processed_activity.assert_called_once_with(
        "activity-2",
        result=ANY,
    )
    result_event = agent_life_service.handle_event.call_args.args[0]
    assert result_event.payload["outcome"] == "completed"
    assert result_event.payload["result_type"] == "no_action"


@pytest.mark.asyncio
async def test_execute_records_failure_and_reraises_planning_error() -> None:
    activity = _activity("activity-3")
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
    activity_manager.complete_processed_activity.assert_called_once_with(
        "activity-3",
        result=ANY,
    )
    result_event = agent_life_service.handle_event.call_args.args[0]
    assert result_event.event_type == AgentEventType.ACTIVITY_RESULT_RECORDED
    assert result_event.payload["outcome"] == "failed"
    action_scheduler.prepare.assert_not_called()
    action_scheduler.execute.assert_not_called()
