from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_ingress_processor import EventIngressProcessor


@pytest.mark.asyncio
async def test_filtered_event_stops_without_side_effects() -> None:
    event_filter = MagicMock()
    event_filter.filter.return_value = None
    activity_manager = MagicMock()
    recorder = MagicMock()
    agent_life_service = MagicMock()
    subscriber_registry = MagicMock()
    subscriber_registry.dispatch = AsyncMock()
    processor = EventIngressProcessor(
        event_filter=event_filter,
        activity_manager=activity_manager,
        conversation_input_recorder=recorder,
        agent_life_service=agent_life_service,
        event_subscriber_registry=subscriber_registry,
    )
    event = AgentEvent(event_type=AgentEventType.USER_TEXT)

    result = await processor.process(event)

    assert result.event is None
    assert result.foreground_at_receipt is None
    assert result.consumed is False
    recorder.record.assert_not_called()
    agent_life_service.handle_event.assert_not_called()
    subscriber_registry.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_preserves_order_and_returns_foreground_snapshot() -> None:
    calls: list[str] = []
    original = AgentEvent(event_type=AgentEventType.USER_TEXT)
    filtered = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "hello"},
    )
    foreground = MagicMock()

    event_filter = MagicMock()
    event_filter.filter.side_effect = lambda event: calls.append("filter") or filtered
    activity_manager = MagicMock()
    activity_manager.foreground_activity = foreground
    recorder = MagicMock()
    recorder.record.side_effect = lambda event: calls.append("record")
    agent_life_service = MagicMock()
    agent_life_service.handle_event.side_effect = lambda event: calls.append("handle")
    subscriber_registry = MagicMock()

    async def dispatch(event: AgentEvent) -> bool:
        calls.append("dispatch")
        return False

    subscriber_registry.dispatch = AsyncMock(side_effect=dispatch)
    processor = EventIngressProcessor(
        event_filter=event_filter,
        activity_manager=activity_manager,
        conversation_input_recorder=recorder,
        agent_life_service=agent_life_service,
        event_subscriber_registry=subscriber_registry,
    )

    result = await processor.process(original)

    assert result.event is filtered
    assert result.foreground_at_receipt is foreground
    assert result.consumed is False
    assert calls == ["filter", "record", "handle", "dispatch"]


@pytest.mark.asyncio
async def test_process_reports_subscriber_consumption() -> None:
    event = AgentEvent(event_type=AgentEventType.APP_STARTED)
    event_filter = MagicMock()
    event_filter.filter.return_value = event
    activity_manager = MagicMock()
    activity_manager.foreground_activity = None
    recorder = MagicMock()
    agent_life_service = MagicMock()
    subscriber_registry = MagicMock()
    subscriber_registry.dispatch = AsyncMock(return_value=True)
    processor = EventIngressProcessor(
        event_filter=event_filter,
        activity_manager=activity_manager,
        conversation_input_recorder=recorder,
        agent_life_service=agent_life_service,
        event_subscriber_registry=subscriber_registry,
    )

    result = await processor.process(event)

    assert result.event is event
    assert result.consumed is True
    recorder.record.assert_called_once_with(event)
    agent_life_service.handle_event.assert_called_once_with(event)
    subscriber_registry.dispatch.assert_awaited_once_with(event)
