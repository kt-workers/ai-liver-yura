from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingEventEnvelope,
    StreamingEventReceiver,
    StreamingEventType,
)


class Gateway:
    closed = False

    def __init__(self, events):
        self.events = events

    async def read_events(self, after=None):
        return self.events

    async def close(self):
        self.closed = True


def test_receiver_preserves_cursor_and_deduplicates_events() -> None:
    async def scenario() -> None:
        source = StreamingEventEnvelope(
            event_id="event-1",
            event_type=StreamingEventType.COMMENT_RECEIVED,
            occurred_at=datetime.now(timezone.utc),
            api_version=CURRENT_STREAMING_API_VERSION,
            payload={"text": "hello"},
        )
        gateway = Gateway((source, source))
        delivered = []

        async def publish(event):
            delivered.append(event)

        receiver = StreamingEventReceiver(gateway, publish, deduplication_capacity=2)
        assert await receiver.run_once() == 1
        assert await receiver.run_once() == 0
        assert receiver.cursor is not None
        assert receiver.cursor.value == "event-1"
        await receiver.stop()
        assert gateway.closed
        assert len(delivered) == 1

    asyncio.run(scenario())
