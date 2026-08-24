from __future__ import annotations

from collections import deque

from .contracts import CandidateLifecycle, PreparedSpeechCandidate
from .runtime import SpeechRuntime


class PreparedSpeechQueue:
    """候補を増殖させない、候補局所のbounded priority queue。"""

    def __init__(self, max_size: int) -> None:
        if type(max_size) is not int or max_size < 1:
            raise ValueError("max_size が不正です")
        self._max_size = max_size
        self._foreground: deque[PreparedSpeechCandidate] = deque()
        self._background: deque[PreparedSpeechCandidate] = deque()

    def __len__(self) -> int:
        return len(self._foreground) + len(self._background)

    def enqueue(self, candidate: PreparedSpeechCandidate, *, foreground: bool) -> bool:
        accepted, _ = self.enqueue_with_suppressed(candidate, foreground=foreground)
        return accepted

    def enqueue_with_suppressed(
        self, candidate: PreparedSpeechCandidate, *, foreground: bool
    ) -> tuple[bool, PreparedSpeechCandidate | None]:
        self.prune()
        if self.contains(candidate.candidate_id):
            return False, None
        suppressed: PreparedSpeechCandidate | None = None
        if len(self) >= self._max_size:
            if foreground and self._background:
                suppressed = self._background.pop()
            else:
                return False, None
        queue = self._foreground if foreground else self._background
        queue.append(candidate)
        return True, suppressed

    def contains(self, candidate_id: str) -> bool:
        return any(
            candidate.candidate_id == candidate_id
            for queue in (self._foreground, self._background)
            for candidate in queue
        )

    def pop(self) -> PreparedSpeechCandidate | None:
        self.prune()
        if self._foreground:
            return self._foreground.popleft()
        return self._background.popleft() if self._background else None

    def remove(self, candidate_id: str) -> None:
        for queue in (self._foreground, self._background):
            for candidate in tuple(queue):
                if candidate.candidate_id == candidate_id:
                    queue.remove(candidate)

    def drain(self) -> tuple[PreparedSpeechCandidate, ...]:
        candidates = tuple(self._foreground) + tuple(self._background)
        self._foreground.clear()
        self._background.clear()
        return candidates

    def prune(self) -> None:
        terminal = {
            CandidateLifecycle.CANCELLED,
            CandidateLifecycle.SUPERSEDED,
            CandidateLifecycle.STALE,
            CandidateLifecycle.REJECTED,
            CandidateLifecycle.FAILED,
            CandidateLifecycle.INTERRUPTED,
            CandidateLifecycle.COMPLETED,
        }
        for queue in (self._foreground, self._background):
            for candidate in tuple(queue):
                if candidate.lifecycle in terminal:
                    queue.remove(candidate)


class PreparedSpeechQueueCoordinator:
    """generation fence後の候補だけをqueue/revalidationへ進める。"""

    def __init__(self, runtime: SpeechRuntime, queue: PreparedSpeechQueue) -> None:
        self._runtime = runtime
        self._queue = queue

    def __len__(self) -> int:
        return len(self._queue)

    async def enqueue_current(
        self, candidate_id: str, generation: int, *, foreground: bool
    ) -> bool:
        if self._queue.contains(candidate_id):
            return False
        candidate = await self._runtime.queue_for_generation(candidate_id, generation)
        if candidate is None:
            return False
        accepted, suppressed = self._queue.enqueue_with_suppressed(candidate, foreground=foreground)
        if not accepted:
            # queueへ入らないcandidateをactiveのまま放置しない。
            await self._runtime.cancel(candidate_id, CandidateLifecycle.SUPERSEDED)
            return False
        if suppressed is not None:
            await self._runtime.cancel(suppressed.candidate_id, CandidateLifecycle.SUPERSEDED)
        return True

    async def pop_for_revalidation(self) -> PreparedSpeechCandidate | None:
        queued = self._queue.pop()
        if queued is None:
            return None
        return await self._runtime.begin_revalidation(queued.candidate_id)

    async def complete_revalidation(
        self,
        candidate_id: str,
        *,
        passed: bool,
        failure: CandidateLifecycle | None = None,
    ) -> PreparedSpeechCandidate:
        return await self._runtime.complete_revalidation(candidate_id, passed, failure)

    def shutdown(self) -> tuple[PreparedSpeechCandidate, ...]:
        return self._queue.drain()
