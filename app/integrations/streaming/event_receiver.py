"""Bounded background receiver for public Streaming events."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable

from app.domain.events import AgentEvent
from app.integrations.streaming.contracts import StreamingCursor
from app.integrations.streaming.errors import StreamingTransportError
from app.integrations.streaming.event_mapper import StreamingEventMapper
from app.integrations.streaming.events import StreamingEventEnvelope


class StreamingEventReceiver:
    def __init__(
        self,
        gateway: object,
        publish: Callable[[AgentEvent], Awaitable[None]],
        *,
        mapper: StreamingEventMapper | None = None,
        poll_interval_seconds: float = 0.5,
        max_backoff_seconds: float = 8.0,
        deduplication_capacity: int = 512,
    ) -> None:
        if poll_interval_seconds <= 0 or max_backoff_seconds <= 0:
            raise ValueError("receiver intervals must be positive")
        if deduplication_capacity < 1:
            raise ValueError("deduplication_capacity must be positive")
        self._gateway = gateway
        self._publish = publish
        self._mapper = mapper or StreamingEventMapper()
        self._poll_interval = poll_interval_seconds
        self._max_backoff = max_backoff_seconds
        self._seen_order: deque[str] = deque()
        self._seen: set[str] = set()
        self._capacity = deduplication_capacity
        self._cursor: StreamingCursor | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def cursor(self) -> StreamingCursor | None:
        return self._cursor

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self.run(), name="streaming-event-receiver")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._gateway.close()  # type: ignore[attr-defined]

    async def run_once(self) -> int:
        events = tuple(
            await self._gateway.read_events(self._cursor)  # type: ignore[attr-defined]
        )
        delivered = 0
        for event in events:
            if not isinstance(event, StreamingEventEnvelope) or event.event_id in self._seen:
                continue
            mapped = self._mapper.map(event)
            self._remember(event.event_id)
            self._cursor = event.cursor or StreamingCursor(event.event_id)
            if mapped is not None:
                await self._publish(mapped)
                delivered += 1
        return delivered

    async def run(self) -> None:
        backoff = self._poll_interval
        while not self._stop.is_set():
            try:
                await self.run_once()
                backoff = self._poll_interval
            except asyncio.CancelledError:
                raise
            except (
                OSError,
                TimeoutError,
                asyncio.TimeoutError,
                StreamingTransportError,
            ):
                backoff = min(self._max_backoff, max(self._poll_interval, backoff * 2))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except (TimeoutError, asyncio.TimeoutError):
                pass

    def _remember(self, event_id: str) -> None:
        self._seen.add(event_id)
        self._seen_order.append(event_id)
        while len(self._seen_order) > self._capacity:
            self._seen.discard(self._seen_order.popleft())
