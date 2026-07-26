from __future__ import annotations

from app.domain.activities import OngoingActivity
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.buffered_event_dispatcher import BufferedEventDispatcher
from app.runtime.event_prioritizer import EventPrioritizer
from app.runtime.user_input_interruption_coordinator import (
    UserInputInterruptionCoordinator,
)
from app.utils.trace import TraceLogger


class EventDispatchProcessor:
    """ルーティング済みイベントの優先度付与とバッファ投入を調停する。"""

    def __init__(
        self,
        *,
        event_prioritizer: EventPrioritizer,
        activity_manager: ActivityManager,
        user_input_interruption_coordinator: UserInputInterruptionCoordinator,
        buffered_event_dispatcher: BufferedEventDispatcher,
        trace_logger: TraceLogger,
    ) -> None:
        self._event_prioritizer = event_prioritizer
        self._activity_manager = activity_manager
        self._user_input_interruption_coordinator = (
            user_input_interruption_coordinator
        )
        self._buffered_event_dispatcher = buffered_event_dispatcher
        self._trace_logger = trace_logger

    def process(
        self,
        *,
        original_event: AgentEvent,
        routed_event: AgentEvent,
        foreground_at_receipt: OngoingActivity | None,
    ) -> AgentEvent:
        self._trace_logger.write(
            "runtime_coordinator:publish_events:filtered",
            event_type=original_event.event_type.value,
            event_id=original_event.event_id,
        )
        prioritized_event = self._event_prioritizer.prioritize(routed_event)
        foreground_before_input = (
            foreground_at_receipt
            if prioritized_event.event_type == AgentEventType.USER_TEXT
            else self._activity_manager.foreground_activity
        )
        self._user_input_interruption_coordinator.after_prioritization(
            prioritized_event,
            foreground_at_receipt=foreground_before_input,
        )
        self._buffered_event_dispatcher.buffer(prioritized_event)
        return prioritized_event
