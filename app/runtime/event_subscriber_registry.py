from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.domain.events import AgentEvent, AgentEventType


EventHandler = Callable[[AgentEvent], Awaitable[object]]
EventPredicate = Callable[[AgentEvent], bool]


class EventSubscriberRegistry:
    """イベント購読者を登録し、最初に一致したハンドラへ配送する。"""

    def __init__(self) -> None:
        self._subscribers: list[
            tuple[AgentEventType, EventHandler, EventPredicate | None]
        ] = []

    def register(
        self,
        event_type: AgentEventType,
        handler: EventHandler,
        *,
        predicate: EventPredicate | None = None,
    ) -> None:
        self._subscribers.append((event_type, handler, predicate))

    async def dispatch(self, event: AgentEvent) -> bool:
        """最初に一致した購読者だけを実行し、処理済みかを返す。"""

        for event_type, handler, predicate in self._subscribers:
            if event.event_type != event_type:
                continue
            if predicate is not None and not predicate(event):
                continue
            await handler(event)
            return True
        return False
