from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.actions import ActionPlanGroup
from app.domain.activities import Activity, ActivityStatus, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.runtime_coordinator import RuntimeCoordinator
from app.runtime.runtime_event_executor import RuntimeEventExecutor
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


def _agent_life_service() -> MagicMock:
    service = MagicMock()
    service.preview_relationship.return_value.as_context.return_value = {
        "affinity": 0.5
    }
    service.agent_state.current_situation.as_context.return_value = {
        "place": "room"
    }
    service.agent_state.memory.as_context.return_value = {"summary": "memory"}
    service.agent_state.current_drive.curiosity = 0.1
    service.agent_state.current_drive.engagement = 0.2
    service.agent_state.current_drive.boredom = 0.3
    service.agent_state.current_drive.energy = 0.4
    service.agent_state.active_activity = None
    service.agent_state.pending_activities = ()
    service.agent_state.suspended_activities = ()
    return service


def _executor(
    *,
    activity_manager: MagicMock | None = None,
    action_planner: AsyncMock | None = None,
    action_scheduler: MagicMock | None = None,
    agent_life_service: MagicMock | None = None,
    enrichers: tuple = (),
) -> RuntimeEventExecutor:
    scheduler = action_scheduler or MagicMock()
    scheduler.prepare = AsyncMock(side_effect=lambda group: group)
    scheduler.execute = AsyncMock(return_value=None)
    return RuntimeEventExecutor(
        activity_manager=activity_manager or MagicMock(),
        action_planner=action_planner or AsyncMock(),
        action_scheduler=scheduler,
        agent_life_service=agent_life_service or _agent_life_service(),
        event_enrichers_provider=lambda: enrichers,
        trace_logger=TraceLogger(),
    )


def test_runtime_context_is_added_without_overwriting_existing_values() -> None:
    service = _agent_life_service()
    executor = _executor(agent_life_service=service)
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"relationship": {"existing": True}},
    )

    enriched = executor._with_runtime_context(event)

    assert enriched.payload["relationship"] == {"existing": True}
    assert enriched.payload["situation"] == {"place": "room"}
    assert enriched.payload["memory"] == {"summary": "memory"}
    service.preview_relationship.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [AgentEventType.SPEECH_STARTED, AgentEventType.SPEECH_FINISHED],
)
async def test_state_only_event_does_not_create_activity(
    event_type: AgentEventType,
) -> None:
    manager = MagicMock()
    planner = AsyncMock()
    scheduler = MagicMock()
    executor = _executor(
        activity_manager=manager,
        action_planner=planner,
        action_scheduler=scheduler,
    )

    result = await executor.execute(AgentEvent(event_type=event_type, payload={}))

    assert result.is_empty()
    assert result.activity_turn_result is None
    manager.handle_event.assert_not_called()
    planner.plan.assert_not_called()
    scheduler.prepare.assert_not_awaited()
    scheduler.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_event_execution_completes_activity_and_syncs_state() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="会話する",
        status=ActivityStatus.ACTIVE,
    )
    manager = MagicMock()
    manager.handle_event.return_value = activity
    manager.get_activity.return_value = activity
    manager.complete_processed_activity.return_value = activity
    planner = AsyncMock()
    planner.plan.return_value = ActionPlanGroup()
    scheduler = MagicMock()
    service = _agent_life_service()
    executor = _executor(
        activity_manager=manager,
        action_planner=planner,
        action_scheduler=scheduler,
        agent_life_service=service,
    )

    result = await executor.execute(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    assert result.is_empty()
    assert result.activity_turn_result is None
    planner.plan.assert_awaited_once_with(activity)
    scheduler.prepare.assert_awaited_once()
    scheduler.execute.assert_awaited_once()
    manager.complete_processed_activity.assert_called_once()
    service.sync_from_activity_manager.assert_called_once_with()


@pytest.mark.asyncio
async def test_action_planning_failure_records_result_and_skips_scheduler() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="会話する",
        status=ActivityStatus.ACTIVE,
    )
    manager = MagicMock()
    manager.handle_event.return_value = activity
    planner = AsyncMock()
    planner.plan.side_effect = RuntimeError("planning failed")
    scheduler = MagicMock()
    service = _agent_life_service()
    executor = _executor(
        activity_manager=manager,
        action_planner=planner,
        action_scheduler=scheduler,
        agent_life_service=service,
    )

    result = await executor.execute(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})
    )

    assert result.activity_turn_result is not None
    manager.record_turn_result.assert_called_once_with(result.activity_turn_result)
    manager.complete_processed_activity.assert_called_once_with(activity.activity_id)
    scheduler.prepare.assert_not_awaited()
    scheduler.execute.assert_not_awaited()
    service.sync_from_activity_manager.assert_called_once_with()


@pytest.mark.asyncio
async def test_runtime_coordinator_delegates_event_execution() -> None:
    event = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={})
    expected = ActionPlanGroup()
    runtime_event_executor = MagicMock()
    runtime_event_executor.execute = AsyncMock(return_value=expected)
    coordinator = RuntimeCoordinator.__new__(RuntimeCoordinator)
    coordinator._runtime_event_executor = runtime_event_executor

    result = await coordinator._handle_event(event)

    assert result is expected
    runtime_event_executor.execute.assert_awaited_once_with(event)
