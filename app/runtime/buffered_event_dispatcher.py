from __future__ import annotations

from app.domain.events import AgentEvent
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_queue import EventQueue
from app.utils.trace import TraceLogger


class BufferedEventDispatcher:
    """優先度付与済みイベントのバッファリングとEventQueueへの排出を担う。"""

    def __init__(
        self,
        *,
        event_buffer: EventBuffer,
        event_queue: EventQueue,
        trace_logger: TraceLogger,
    ) -> None:
        self._event_buffer = event_buffer
        self._event_queue = event_queue
        self._trace_logger = trace_logger

    def buffer(self, event: AgentEvent) -> None:
        self._trace_logger.write(
            "runtime_coordinator:publish_events:prioritized",
            event_type=event.event_type.value,
            event_id=event.event_id,
            priority=event.priority,
            discardable=event.discardable,
            replace_key=event.replace_key,
        )
        self._event_buffer.put(event)

    async def flush(self) -> None:
        for event in self._event_buffer.drain():
            self._trace_logger.write(
                "runtime_coordinator:publish_events:queue_put",
                event_type=event.event_type.value,
                event_id=event.event_id,
                priority=event.priority,
                discardable=event.discardable,
                replace_key=event.replace_key,
                queue_empty_before_put=self._event_queue.empty(),
            )
            await self._event_queue.put(event)
