from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.user_input_event_logger import UserInputEventLogger
from app.runtime.user_input_event_router import UserInputEventRouter
from app.runtime.user_input_interruption_coordinator import (
    UserInputInterruptionCoordinator,
)


class EventTypeRouter:
    """イベント種別に応じたRuntime内ルーティングの選択を担う。"""

    def __init__(
        self,
        *,
        user_input_interruption_coordinator: UserInputInterruptionCoordinator,
        user_input_event_logger: UserInputEventLogger,
        user_input_event_router: UserInputEventRouter,
        behavior_router: Callable[[AgentEvent], Awaitable[AgentEvent | None]],
        behavior_routing_available: Callable[[], bool],
    ) -> None:
        self._user_input_interruption_coordinator = (
            user_input_interruption_coordinator
        )
        self._user_input_event_logger = user_input_event_logger
        self._user_input_event_router = user_input_event_router
        self._behavior_router = behavior_router
        self._behavior_routing_available = behavior_routing_available

    async def route(
        self,
        event: AgentEvent,
        *,
        foreground_at_receipt: object | None,
    ) -> AgentEvent | None:
        if event.event_type == AgentEventType.USER_TEXT:
            self._user_input_interruption_coordinator.before_routing(
                event,
                foreground_at_receipt=foreground_at_receipt,
            )
            self._user_input_event_logger.log(event)
            return await self._user_input_event_router.route(event)

        if (
            event.event_type == AgentEventType.APP_STARTED
            and self._behavior_routing_available()
        ):
            return await self._behavior_router(event)

        return event
