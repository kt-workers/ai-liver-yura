from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.domain.events import AgentEvent


AsyncEventRouter = Callable[[AgentEvent], Awaitable[AgentEvent | None]]
EventFallback = Callable[[AgentEvent], AgentEvent]
AvailabilityCheck = Callable[[], bool]


class UserInputEventRouter:
    """USER_TEXTのルーティング経路選択を担う。"""

    def __init__(
        self,
        *,
        behavior_router: AsyncEventRouter,
        plugin_router: AsyncEventRouter,
        fallback: EventFallback,
        behavior_routing_available: AvailabilityCheck,
        plugin_routing_available: AvailabilityCheck,
    ) -> None:
        self._behavior_router = behavior_router
        self._plugin_router = plugin_router
        self._fallback = fallback
        self._behavior_routing_available = behavior_routing_available
        self._plugin_routing_available = plugin_routing_available

    async def route(self, event: AgentEvent) -> AgentEvent | None:
        if self._behavior_routing_available():
            return await self._behavior_router(event)
        if self._plugin_routing_available():
            return await self._plugin_router(event)
        return self._fallback(event)
