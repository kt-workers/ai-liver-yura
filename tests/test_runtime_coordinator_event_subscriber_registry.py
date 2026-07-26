from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from app.domain.events import AgentEvent, AgentEventType
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
async def test_runtime_coordinator_delegates_event_subscription_and_dispatch(
    runtime_components,
) -> None:
    registry = StubEventSubscriberRegistry()
    coordinator = RuntimeCoordinator(
        runtime_components.event_queue,
        runtime_components.activity_manager,
        runtime_components.action_planner,
        runtime_components.action_scheduler,
        runtime_components.activity_planning_request_queue,
        runtime_components.activity_planner_thread,
        runtime_components.activity_executor_thread,
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
    assert runtime_components.event_queue.empty()
