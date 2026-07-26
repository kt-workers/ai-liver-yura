from __future__ import annotations

from app.domain.events import AgentEvent
from app.utils.trace import TraceLogger


class UserInputEventLogger:
    """USER_TEXT受信時の構造化トレース出力を担う。"""

    def __init__(self, trace_logger: TraceLogger) -> None:
        self._trace_logger = trace_logger

    def log(self, event: AgentEvent) -> None:
        source = str(event.payload.get("source") or "unknown")
        self._trace_logger.info(
            "runtime_coordinator:event_received",
            **event.trace_context.as_log_fields(),
            event_type=event.event_type.value,
            source=source,
            priority=event.priority,
        )
        self._trace_logger.user_input(
            source=source,
            event_id=event.event_id,
            text=str(event.payload.get("text") or ""),
            trace_id=event.trace_context.trace_id,
            parent_trace_id=event.trace_context.parent_trace_id,
            activity_turn_id=event.trace_context.activity_turn_id,
            confirmation_id=event.trace_context.confirmation_id,
        )
