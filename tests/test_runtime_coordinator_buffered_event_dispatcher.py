from __future__ import annotations

from queue import Queue
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.event_queue import EventQueue
from app.runtime.runtime_coordinator import RuntimeCoordinator


@pytest.mark.asyncio
async def test_runtime_coordinator_delegates_buffering_and_flush() -> None:
    dispatcher = MagicMock()
    dispatcher.flush = AsyncMock()
    event_queue = EventQueue()
    activity_manager = ActivityManager()
    agent_life_service = MagicMock()
    agent_life_service.agent_state = MagicMock()

    coordinator = RuntimeCoordinator(
        event_queue=event_queue,
        activity_manager=activity_manager,
        action_planner=MagicMock(),
        action_scheduler=MagicMock(),
        activity_planning_request_queue=Queue(),
        activity_planner_thread=MagicMock(),
        activity_executor_thread=MagicMock(),
        agent_life_service=agent_life_service,
        buffered_event_dispatcher=dispatcher,
    )
    event = AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT, payload={})

    await coordinator.publish_event(event)

    dispatcher.buffer.assert_called_once()
    buffered_event = dispatcher.buffer.call_args.args[0]
    assert buffered_event.event_id == event.event_id
    dispatcher.flush.assert_awaited_once_with()
