from __future__ import annotations

import asyncio
from collections import deque
from typing import Protocol

from app.subsystems.streaming.contracts import (
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExternalObservation,
)


class StreamingProviderPort(Protocol):
    async def execute(self, request: StreamingExecutionRequest) -> StreamingExecutionReport: ...


class StreamingSubsystemRuntime:
    """provider I/OをCoreから隔離し、観測とコメント信号をboundedに扱う。"""

    def __init__(self, provider: StreamingProviderPort, *, comment_limit: int = 64) -> None:
        if type(comment_limit) is not int or comment_limit < 1:
            raise ValueError("comment_limit が不正です")
        self._provider = provider
        self._observations: dict[str, StreamingExternalObservation] = {}
        self._comments: deque[str] = deque(maxlen=comment_limit)
        self._tasks: set[asyncio.Task[object]] = set()

    async def execute(self, request: StreamingExecutionRequest) -> StreamingExecutionReport:
        return await self._provider.execute(request)

    def accept_observation(self, observation: StreamingExternalObservation) -> bool:
        current = self._observations.get(observation.source_ref)
        if current is not None and observation.provider_generation < current.provider_generation:
            return False
        self._observations[observation.source_ref] = observation
        return True

    def ingest_comment_signal(self, signal_ref: str) -> None:
        if not isinstance(signal_ref, str) or not signal_ref.strip():
            raise ValueError("signal_ref が不正です")
        self._comments.append(signal_ref)

    def drain_comment_signals(self) -> tuple[str, ...]:
        signals = tuple(self._comments)
        self._comments.clear()
        return signals

    async def shutdown(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    @property
    def pending_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks)
