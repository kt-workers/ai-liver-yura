from __future__ import annotations

from .queue import PreparedSpeechQueueCoordinator
from .runtime import SpeechRuntime
from .tasks import CandidateTaskRegistry


class SpeechRuntimeShutdown:
    """candidate局所task・queue・lifecycleを一回で収束させる。"""

    def __init__(
        self,
        runtime: SpeechRuntime,
        tasks: CandidateTaskRegistry,
        queue: PreparedSpeechQueueCoordinator,
    ) -> None:
        self._runtime = runtime
        self._tasks = tasks
        self._queue = queue

    async def close(self) -> tuple[str, ...]:
        self._queue.shutdown()
        await self._tasks.shutdown()
        return await self._runtime.shutdown()
