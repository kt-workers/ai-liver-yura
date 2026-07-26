from __future__ import annotations

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_subscriber_registry import EventSubscriberRegistry


@pytest.mark.asyncio
async def test_dispatch_returns_false_when_no_subscriber_matches() -> None:
    registry = EventSubscriberRegistry()

    handled = await registry.dispatch(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "hello"})
    )

    assert handled is False


@pytest.mark.asyncio
async def test_dispatch_invokes_only_first_matching_subscriber() -> None:
    registry = EventSubscriberRegistry()
    calls: list[str] = []

    async def first(event: AgentEvent) -> object:
        calls.append(f"first:{event.event_id}")
        return None

    async def second(event: AgentEvent) -> object:
        calls.append(f"second:{event.event_id}")
        return None

    registry.register(AgentEventType.USER_TEXT, first)
    registry.register(AgentEventType.USER_TEXT, second)
    event = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "hello"})

    handled = await registry.dispatch(event)

    assert handled is True
    assert calls == [f"first:{event.event_id}"]


@pytest.mark.asyncio
async def test_dispatch_skips_subscriber_when_predicate_is_false() -> None:
    registry = EventSubscriberRegistry()
    calls: list[str] = []

    async def skipped(event: AgentEvent) -> object:
        calls.append("skipped")
        return None

    async def accepted(event: AgentEvent) -> object:
        calls.append("accepted")
        return None

    registry.register(
        AgentEventType.USER_TEXT,
        skipped,
        predicate=lambda event: event.payload.get("source") == "youtube",
    )
    registry.register(AgentEventType.USER_TEXT, accepted)

    handled = await registry.dispatch(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "hello", "source": "console"},
        )
    )

    assert handled is True
    assert calls == ["accepted"]


@pytest.mark.asyncio
async def test_dispatch_does_not_invoke_different_event_type() -> None:
    registry = EventSubscriberRegistry()
    calls: list[str] = []

    async def handler(event: AgentEvent) -> object:
        calls.append(event.event_type.value)
        return None

    registry.register(AgentEventType.APP_STARTED, handler)

    handled = await registry.dispatch(
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "hello"})
    )

    assert handled is False
    assert calls == []
