from __future__ import annotations

from .discard import PreparedAudioDiscarder, PreparedAudioDiscardReason
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
        discarder: PreparedAudioDiscarder,
    ) -> None:
        self._runtime = runtime
        self._tasks = tasks
        self._queue = queue
        self._discarder = discarder

    async def close(self) -> tuple[str, ...]:
        self._queue.shutdown()
        await self._tasks.shutdown()
        for candidate_id in await self._runtime.active_candidate_ids():
            generation = self._runtime.generation(candidate_id)
            await self._discarder.discard_current(
                candidate_id, generation, PreparedAudioDiscardReason.CANDIDATE_CANCELLED
            )
        return await self._runtime.shutdown()
