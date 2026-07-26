from __future__ import annotations

from dataclasses import dataclass

from app.domain.activities import Activity
from app.domain.events import AgentEvent
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.conversation_input_recorder import ConversationInputRecorder
from app.runtime.event_filter import EventFilter
from app.runtime.event_subscriber_registry import EventSubscriberRegistry


@dataclass(frozen=True)
class EventIngressResult:
    """イベント入口処理の結果。"""

    event: AgentEvent | None
    foreground_at_receipt: Activity | None
    consumed: bool = False


class EventIngressProcessor:
    """イベントのフィルタリングと入口側の副作用をまとめて処理する。"""

    def __init__(
        self,
        *,
        event_filter: EventFilter,
        activity_manager: ActivityManager,
        conversation_input_recorder: ConversationInputRecorder,
        agent_life_service: AgentLifeService,
        event_subscriber_registry: EventSubscriberRegistry,
    ) -> None:
        self._event_filter = event_filter
        self._activity_manager = activity_manager
        self._conversation_input_recorder = conversation_input_recorder
        self._agent_life_service = agent_life_service
        self._event_subscriber_registry = event_subscriber_registry

    async def process(self, event: AgentEvent) -> EventIngressResult:
        filtered_event = self._event_filter.filter(event)
        if filtered_event is None:
            return EventIngressResult(
                event=None,
                foreground_at_receipt=None,
                consumed=False,
            )

        foreground_at_receipt = self._activity_manager.foreground_activity
        self._conversation_input_recorder.record(filtered_event)
        self._agent_life_service.handle_event(filtered_event)
        consumed = await self._event_subscriber_registry.dispatch(filtered_event)

        return EventIngressResult(
            event=filtered_event,
            foreground_at_receipt=foreground_at_receipt,
            consumed=consumed,
        )
