from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .contracts import CandidateLifecycle, PreparedSpeechCandidate
from .runtime import SpeechRuntime


@dataclass(frozen=True, slots=True)
class PreparedSpeechQueueEntry:
    candidate_id: str
    generation: int
    foreground: bool
    enqueue_sequence: int

    def __post_init__(self) -> None:
        if not self.candidate_id or type(self.generation) is not int or self.generation < 1:
            raise ValueError("queue entry が不正です")
        if type(self.foreground) is not bool or self.enqueue_sequence < 1:
            raise ValueError("queue entry が不正です")


class PreparedSpeechQueue:
    """候補を増殖させない、候補局所のbounded priority queue。"""

    def __init__(self, max_size: int, max_consecutive_foreground: int = 3) -> None:
        if type(max_size) is not int or max_size < 1:
            raise ValueError("max_size が不正です")
        if type(max_consecutive_foreground) is not int or max_consecutive_foreground < 1:
            raise ValueError("max_consecutive_foreground が不正です")
        self._max_size = max_size
        self._max_consecutive_foreground = max_consecutive_foreground
        self._consecutive_foreground = 0
        self._foreground: deque[PreparedSpeechQueueEntry] = deque()
        self._background: deque[PreparedSpeechQueueEntry] = deque()
        self._next_sequence = 1

    def __len__(self) -> int:
        return len(self._foreground) + len(self._background)

    def enqueue(self, candidate_id: str, generation: int, *, foreground: bool) -> bool:
        accepted, _ = self.enqueue_with_suppressed(candidate_id, generation, foreground=foreground)
        return accepted

    def enqueue_with_suppressed(
        self, candidate_id: str, generation: int, *, foreground: bool
    ) -> tuple[bool, PreparedSpeechQueueEntry | None]:
        self.prune()
        if self.contains(candidate_id):
            return False, None
        suppressed: PreparedSpeechQueueEntry | None = None
        if len(self) >= self._max_size:
            if foreground and self._background:
                suppressed = self._background.pop()
            else:
                return False, None
        queue = self._foreground if foreground else self._background
        queue.append(
            PreparedSpeechQueueEntry(candidate_id, generation, foreground, self._next_sequence)
        )
        self._next_sequence += 1
        return True, suppressed

    def contains(self, candidate_id: str) -> bool:
        return any(
            entry.candidate_id == candidate_id
            for queue in (self._foreground, self._background)
            for entry in queue
        )

    def pop(self) -> PreparedSpeechQueueEntry | None:
        self.prune()
        if self._foreground and (
            not self._background or self._consecutive_foreground < self._max_consecutive_foreground
        ):
            self._consecutive_foreground += 1
            return self._foreground.popleft()
        if self._background:
            self._consecutive_foreground = 0
            return self._background.popleft()
        return None

    def remove(self, candidate_id: str) -> None:
        for queue in (self._foreground, self._background):
            for candidate in tuple(queue):
                if candidate.candidate_id == candidate_id:
                    queue.remove(candidate)

    def drain(self) -> tuple[PreparedSpeechQueueEntry, ...]:
        candidates = tuple(self._foreground) + tuple(self._background)
        self._foreground.clear()
        self._background.clear()
        return candidates

    def prune(self) -> None:
        """live lifecycleの評価はPreparedSpeechQueueCoordinatorだけが行う。"""


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
        accepted, suppressed = self._queue.enqueue_with_suppressed(
            candidate_id, generation, foreground=foreground
        )
        if not accepted:
            # queueへ入らないcandidateをactiveのまま放置しない。
            await self._runtime.cancel(candidate_id, CandidateLifecycle.SUPERSEDED)
            return False
        if suppressed is not None:
            await self._runtime.cancel(suppressed.candidate_id, CandidateLifecycle.SUPERSEDED)
        return True

    async def pop_for_revalidation(self) -> PreparedSpeechCandidate | None:
        while (entry := self._queue.pop()) is not None:
            live = await self._runtime.candidate(entry.candidate_id)
            if (
                self._runtime.generation(entry.candidate_id) != entry.generation
                or live.candidate_id != entry.candidate_id
                or live.lifecycle is not CandidateLifecycle.QUEUED
            ):
                continue
            return await self._runtime.begin_revalidation(entry.candidate_id)
        return None

    async def complete_revalidation(
        self,
        candidate_id: str,
        *,
        passed: bool,
        failure: CandidateLifecycle | None = None,
    ) -> PreparedSpeechCandidate:
        return await self._runtime.complete_revalidation(candidate_id, passed, failure)

    def shutdown(self) -> tuple[PreparedSpeechQueueEntry, ...]:
        return self._queue.drain()
