from __future__ import annotations

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.buffered_event_dispatcher import BufferedEventDispatcher
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_queue import EventQueue
from app.utils.trace import TraceLogger


@pytest.mark.asyncio
async def test_flush_moves_buffered_events_to_event_queue() -> None:
    event_buffer = EventBuffer()
    event_queue = EventQueue()
    dispatcher = BufferedEventDispatcher(
        event_buffer=event_buffer,
        event_queue=event_queue,
        trace_logger=TraceLogger(),
    )
    first = AgentEvent(event_type=AgentEventType.USER_TEXT, priority=10)
    second = AgentEvent(event_type=AgentEventType.APP_STARTED, priority=20)

    dispatcher.buffer(first)
    dispatcher.buffer(second)
    await dispatcher.flush()

    assert event_buffer.is_empty()
    assert await event_queue.get() == second
    assert await event_queue.get() == first


@pytest.mark.asyncio
async def test_buffer_keeps_only_latest_event_for_same_replace_key() -> None:
    event_buffer = EventBuffer()
    event_queue = EventQueue()
    dispatcher = BufferedEventDispatcher(
        event_buffer=event_buffer,
        event_queue=event_queue,
        trace_logger=TraceLogger(),
    )
    old = AgentEvent(
        event_type=AgentEventType.CAMERA_FRAME,
        payload={"frame_id": "old"},
        replace_key="camera_frame",
    )
    new = AgentEvent(
        event_type=AgentEventType.CAMERA_FRAME,
        payload={"frame_id": "new"},
        replace_key="camera_frame",
    )

    dispatcher.buffer(old)
    dispatcher.buffer(new)
    await dispatcher.flush()

    assert await event_queue.get() == new
    assert event_queue.empty()
