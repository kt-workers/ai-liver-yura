from __future__ import annotations

from collections.abc import Awaitable, Callable
from queue import Queue
from unittest.mock import MagicMock

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_planner_thread import ActivityPlanningRequest
from app.runtime.event_queue import EventQueue
from app.runtime.runtime_coordinator import RuntimeCoordinator


class StubEventSubscriberRegistry:
    def __init__(self) -> None:
        self.registrations: list[
            tuple[
                AgentEventType,
                Callable[[AgentEvent], Awaitable[object]],
                Callable[[AgentEvent], bool] | None,
            ]
        ] = []
        self.dispatched: list[AgentEvent] = []
        self.handled = True

    def register(
        self,
        event_type: AgentEventType,
        handler: Callable[[AgentEvent], Awaitable[object]],
        *,
        predicate: Callable[[AgentEvent], bool] | None = None,
    ) -> None:
        self.registrations.append((event_type, handler, predicate))

    async def dispatch(self, event: AgentEvent) -> bool:
        self.dispatched.append(event)
        return self.handled


@pytest.mark.asyncio
async def test_runtime_coordinator_delegates_event_subscription_and_dispatch() -> None:
    registry = StubEventSubscriberRegistry()
    event_queue = EventQueue()
    activity_manager = MagicMock()
    activity_manager.foreground_activity = None
    agent_life_service = MagicMock()

    coordinator = RuntimeCoordinator(
        event_queue,
        activity_manager,
        MagicMock(),
        MagicMock(),
        Queue[ActivityPlanningRequest](),
        MagicMock(),
        MagicMock(),
        agent_life_service=agent_life_service,
        event_subscriber_registry=registry,  # type: ignore[arg-type]
    )

    async def handler(event: AgentEvent) -> object:
        return None

    predicate = lambda event: event.payload.get("source") == "console"
    coordinator.subscribe_event(
        AgentEventType.USER_TEXT,
        handler,
        predicate=predicate,
    )
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "hello", "source": "console"},
    )

    await coordinator.publish_event(event)

    assert registry.registrations == [
        (AgentEventType.USER_TEXT, handler, predicate)
    ]
    assert registry.dispatched == [event]
    assert event_queue.empty()
    agent_life_service.handle_event.assert_called_once_with(event)
