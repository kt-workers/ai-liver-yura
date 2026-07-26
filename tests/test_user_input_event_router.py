from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.user_input_event_router import UserInputEventRouter


@pytest.mark.asyncio
async def test_route_uses_behavior_router_first() -> None:
    event = AgentEvent(event_type=AgentEventType.USER_TEXT)
    routed = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"route": "behavior"})
    behavior_router = AsyncMock(return_value=routed)
    plugin_router = AsyncMock()
    fallback = Mock()
    router = UserInputEventRouter(
        behavior_router=behavior_router,
        plugin_router=plugin_router,
        fallback=fallback,
        behavior_routing_available=lambda: True,
        plugin_routing_available=lambda: True,
    )

    assert await router.route(event) == routed
    behavior_router.assert_awaited_once_with(event)
    plugin_router.assert_not_awaited()
    fallback.assert_not_called()


@pytest.mark.asyncio
async def test_route_uses_plugin_router_when_behavior_is_unavailable() -> None:
    event = AgentEvent(event_type=AgentEventType.USER_TEXT)
    routed = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"route": "plugin"})
    behavior_router = AsyncMock()
    plugin_router = AsyncMock(return_value=routed)
    fallback = Mock()
    router = UserInputEventRouter(
        behavior_router=behavior_router,
        plugin_router=plugin_router,
        fallback=fallback,
        behavior_routing_available=lambda: False,
        plugin_routing_available=lambda: True,
    )

    assert await router.route(event) == routed
    behavior_router.assert_not_awaited()
    plugin_router.assert_awaited_once_with(event)
    fallback.assert_not_called()


@pytest.mark.asyncio
async def test_route_uses_fallback_when_no_router_is_available() -> None:
    event = AgentEvent(event_type=AgentEventType.USER_TEXT)
    routed = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"route": "fallback"})
    behavior_router = AsyncMock()
    plugin_router = AsyncMock()
    fallback = Mock(return_value=routed)
    router = UserInputEventRouter(
        behavior_router=behavior_router,
        plugin_router=plugin_router,
        fallback=fallback,
        behavior_routing_available=lambda: False,
        plugin_routing_available=lambda: False,
    )

    assert await router.route(event) == routed
    behavior_router.assert_not_awaited()
    plugin_router.assert_not_awaited()
    fallback.assert_called_once_with(event)
