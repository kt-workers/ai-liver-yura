from __future__ import annotations

from typing import Any

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.user_input_event_logger import UserInputEventLogger


class StubTraceLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, dict[str, Any]]] = []
        self.user_input_calls: list[dict[str, Any]] = []

    def info(self, event_name: str, **fields: Any) -> None:
        self.info_calls.append((event_name, fields))

    def user_input(self, **fields: Any) -> None:
        self.user_input_calls.append(fields)


def test_log_writes_event_received_and_user_input_with_existing_fields() -> None:
    trace_logger = StubTraceLogger()
    logger = UserInputEventLogger(trace_logger)  # type: ignore[arg-type]
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは", "source": "console"},
        priority=42,
    )

    logger.log(event)

    assert len(trace_logger.info_calls) == 1
    event_name, info_fields = trace_logger.info_calls[0]
    assert event_name == "runtime_coordinator:event_received"
    assert info_fields["event_type"] == AgentEventType.USER_TEXT.value
    assert info_fields["source"] == "console"
    assert info_fields["priority"] == 42

    assert trace_logger.user_input_calls == [
        {
            "source": "console",
            "event_id": event.event_id,
            "text": "こんにちは",
            "trace_id": event.trace_context.trace_id,
            "parent_trace_id": event.trace_context.parent_trace_id,
            "activity_turn_id": event.trace_context.activity_turn_id,
            "confirmation_id": event.trace_context.confirmation_id,
        }
    ]


def test_log_uses_existing_fallbacks_for_missing_source_and_text() -> None:
    trace_logger = StubTraceLogger()
    logger = UserInputEventLogger(trace_logger)  # type: ignore[arg-type]
    event = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={})

    logger.log(event)

    assert trace_logger.info_calls[0][1]["source"] == "unknown"
    assert trace_logger.user_input_calls[0]["source"] == "unknown"
    assert trace_logger.user_input_calls[0]["text"] == ""
