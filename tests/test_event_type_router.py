from __future__ import annotations

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_type_router import EventTypeRouter


class _InterruptionCoordinator:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.foreground_at_receipt: object | None = None

    def before_routing(
        self,
        event: AgentEvent,
        *,
        foreground_at_receipt: object | None,
    ) -> None:
        self._calls.append("before_routing")
        self.foreground_at_receipt = foreground_at_receipt


class _Logger:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def log(self, event: AgentEvent) -> None:
        self._calls.append("log")


class _UserInputRouter:
    def __init__(
        self,
        calls: list[str],
        result: AgentEvent | None,
    ) -> None:
        self._calls = calls
        self._result = result

    async def route(self, event: AgentEvent) -> AgentEvent | None:
        self._calls.append("user_route")
        return self._result


@pytest.mark.asyncio
async def test_user_text_runs_interruption_logging_and_routing_in_order() -> None:
    calls: list[str] = []
    source = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )
    routed = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは", "routed": True},
    )
    foreground = object()
    interruption = _InterruptionCoordinator(calls)
    router = EventTypeRouter(
        user_input_interruption_coordinator=interruption,  # type: ignore[arg-type]
        user_input_event_logger=_Logger(calls),  # type: ignore[arg-type]
        user_input_event_router=_UserInputRouter(calls, routed),  # type: ignore[arg-type]
        behavior_router=lambda event: _unexpected_behavior_route(event),
        behavior_routing_available=lambda: True,
    )

    result = await router.route(source, foreground_at_receipt=foreground)

    assert result is routed
    assert calls == ["before_routing", "log", "user_route"]
    assert interruption.foreground_at_receipt is foreground


@pytest.mark.asyncio
async def test_user_text_preserves_none_result_from_user_input_router() -> None:
    calls: list[str] = []
    source = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "中止"},
    )
    router = EventTypeRouter(
        user_input_interruption_coordinator=_InterruptionCoordinator(calls),  # type: ignore[arg-type]
        user_input_event_logger=_Logger(calls),  # type: ignore[arg-type]
        user_input_event_router=_UserInputRouter(calls, None),  # type: ignore[arg-type]
        behavior_router=lambda event: _unexpected_behavior_route(event),
        behavior_routing_available=lambda: True,
    )

    assert await router.route(source, foreground_at_receipt=None) is None


@pytest.mark.asyncio
async def test_app_started_uses_behavior_router_when_available() -> None:
    calls: list[str] = []
    source = AgentEvent(event_type=AgentEventType.APP_STARTED, payload={})
    routed = AgentEvent(
        event_type=AgentEventType.APP_STARTED,
        payload={"planned": True},
    )

    async def behavior_route(event: AgentEvent) -> AgentEvent | None:
        calls.append("behavior_route")
        return routed

    router = EventTypeRouter(
        user_input_interruption_coordinator=_InterruptionCoordinator(calls),  # type: ignore[arg-type]
        user_input_event_logger=_Logger(calls),  # type: ignore[arg-type]
        user_input_event_router=_UserInputRouter(calls, source),  # type: ignore[arg-type]
        behavior_router=behavior_route,
        behavior_routing_available=lambda: True,
    )

    assert await router.route(source, foreground_at_receipt=None) is routed
    assert calls == ["behavior_route"]


@pytest.mark.asyncio
async def test_app_started_passes_through_when_behavior_routing_is_unavailable() -> None:
    calls: list[str] = []
    source = AgentEvent(event_type=AgentEventType.APP_STARTED, payload={})
    router = EventTypeRouter(
        user_input_interruption_coordinator=_InterruptionCoordinator(calls),  # type: ignore[arg-type]
        user_input_event_logger=_Logger(calls),  # type: ignore[arg-type]
        user_input_event_router=_UserInputRouter(calls, source),  # type: ignore[arg-type]
        behavior_router=lambda event: _unexpected_behavior_route(event),
        behavior_routing_available=lambda: False,
    )

    assert await router.route(source, foreground_at_receipt=None) is source
    assert calls == []


@pytest.mark.asyncio
async def test_other_event_types_pass_through_without_routing() -> None:
    calls: list[str] = []
    source = AgentEvent(event_type=AgentEventType.SYSTEM_STOPPED, payload={})
    router = EventTypeRouter(
        user_input_interruption_coordinator=_InterruptionCoordinator(calls),  # type: ignore[arg-type]
        user_input_event_logger=_Logger(calls),  # type: ignore[arg-type]
        user_input_event_router=_UserInputRouter(calls, source),  # type: ignore[arg-type]
        behavior_router=lambda event: _unexpected_behavior_route(event),
        behavior_routing_available=lambda: True,
    )

    assert await router.route(source, foreground_at_receipt=None) is source
    assert calls == []


async def _unexpected_behavior_route(event: AgentEvent) -> AgentEvent | None:
    raise AssertionError("behavior router should not be called")
