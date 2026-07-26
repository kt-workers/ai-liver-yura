from __future__ import annotations

from typing import Any, cast

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.event_dispatch_processor import EventDispatchProcessor


class RecordingPrioritizer:
    def __init__(self, result: AgentEvent, calls: list[str]) -> None:
        self._result = result
        self._calls = calls
        self.received: AgentEvent | None = None

    def prioritize(self, event: AgentEvent) -> AgentEvent:
        self._calls.append("prioritize")
        self.received = event
        return self._result


class RecordingActivityManager:
    def __init__(self, foreground: object) -> None:
        self.foreground_activity = foreground


class RecordingInterruptionCoordinator:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.received: tuple[AgentEvent, object | None] | None = None

    def after_prioritization(
        self,
        event: AgentEvent,
        *,
        foreground_at_receipt: object | None,
    ) -> None:
        self._calls.append("after_prioritization")
        self.received = (event, foreground_at_receipt)


class RecordingDispatcher:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.events: list[AgentEvent] = []

    def buffer(self, event: AgentEvent) -> None:
        self._calls.append("buffer")
        self.events.append(event)


class RecordingTraceLogger:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.records: list[tuple[str, dict[str, object]]] = []

    def write(self, event_name: str, **fields: object) -> None:
        self._calls.append("trace")
        self.records.append((event_name, fields))


def build_processor(
    *,
    prioritized_event: AgentEvent,
    current_foreground: object,
    calls: list[str],
) -> tuple[
    EventDispatchProcessor,
    RecordingPrioritizer,
    RecordingInterruptionCoordinator,
    RecordingDispatcher,
    RecordingTraceLogger,
]:
    prioritizer = RecordingPrioritizer(prioritized_event, calls)
    interruption = RecordingInterruptionCoordinator(calls)
    dispatcher = RecordingDispatcher(calls)
    trace_logger = RecordingTraceLogger(calls)
    processor = EventDispatchProcessor(
        event_prioritizer=cast(Any, prioritizer),
        activity_manager=cast(Any, RecordingActivityManager(current_foreground)),
        user_input_interruption_coordinator=cast(Any, interruption),
        buffered_event_dispatcher=cast(Any, dispatcher),
        trace_logger=cast(Any, trace_logger),
    )
    return processor, prioritizer, interruption, dispatcher, trace_logger


def test_process_prioritizes_and_buffers_in_existing_order() -> None:
    calls: list[str] = []
    original = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "original"},
    )
    routed = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "routed"},
    )
    prioritized = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "prioritized"},
    )
    foreground_at_receipt = object()
    processor, prioritizer, interruption, dispatcher, trace_logger = build_processor(
        prioritized_event=prioritized,
        current_foreground=object(),
        calls=calls,
    )

    result = processor.process(
        original_event=original,
        routed_event=routed,
        foreground_at_receipt=cast(Any, foreground_at_receipt),
    )

    assert result is prioritized
    assert prioritizer.received is routed
    assert interruption.received == (prioritized, foreground_at_receipt)
    assert dispatcher.events == [prioritized]
    assert trace_logger.records == [
        (
            "runtime_coordinator:publish_events:filtered",
            {
                "event_type": original.event_type.value,
                "event_id": original.event_id,
            },
        )
    ]
    assert calls == ["trace", "prioritize", "after_prioritization", "buffer"]


def test_non_user_event_uses_current_foreground_after_prioritization() -> None:
    calls: list[str] = []
    event = AgentEvent(event_type=AgentEventType.APP_STARTED, payload={})
    prioritized = AgentEvent(event_type=AgentEventType.APP_STARTED, payload={})
    current_foreground = object()
    receipt_foreground = object()
    processor, _, interruption, dispatcher, _ = build_processor(
        prioritized_event=prioritized,
        current_foreground=current_foreground,
        calls=calls,
    )

    processor.process(
        original_event=event,
        routed_event=event,
        foreground_at_receipt=cast(Any, receipt_foreground),
    )

    assert interruption.received == (prioritized, current_foreground)
    assert dispatcher.events == [prioritized]
