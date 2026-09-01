from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .contracts import CandidateLifecycle, PreparedSpeechCandidate
from .discard import PreparedAudioDiscarder, PreparedAudioDiscardReason
from .policy import SpeechRuntimeOperationalPolicy, V2_SPEECH_RUNTIME_OPERATIONAL_POLICY
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

    def __init__(
        self,
        max_size: int | SpeechRuntimeOperationalPolicy = V2_SPEECH_RUNTIME_OPERATIONAL_POLICY,
        max_consecutive_foreground: int | None = None,
    ) -> None:
        if isinstance(max_size, SpeechRuntimeOperationalPolicy):
            if max_consecutive_foreground is not None:
                raise ValueError("Policy指定時に個別queue値を上書きできません")
            policy = max_size
            resolved_size = policy.queue_max_candidates
            resolved_foreground = policy.queue_max_consecutive_foreground
        else:
            if type(max_size) is not int or max_size < 1:
                raise ValueError("max_size が不正です")
            resolved_size = max_size
            resolved_foreground = 3 if max_consecutive_foreground is None else max_consecutive_foreground
            if type(resolved_foreground) is not int or resolved_foreground < 1:
                raise ValueError("max_consecutive_foreground が不正です")
            policy = None
        self._policy = policy
        self._max_size = resolved_size
        self._max_consecutive_foreground = resolved_foreground
        self._consecutive_foreground = 0
        self._foreground: deque[PreparedSpeechQueueEntry] = deque()
        self._background: deque[PreparedSpeechQueueEntry] = deque()
        self._next_sequence = 1

    @property
    def policy(self) -> SpeechRuntimeOperationalPolicy | None:
        return self._policy

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

    def __init__(
        self,
        runtime: SpeechRuntime,
        queue: PreparedSpeechQueue,
        discarder: PreparedAudioDiscarder,
    ) -> None:
        self._runtime = runtime
        self._queue = queue
        self._discarder = discarder

    def __len__(self) -> int:
        return len(self._queue)

    async def enqueue_current(
        self, candidate_id: str, generation: int, *, foreground: bool
    ) -> bool:
        if self._queue.contains(candidate_id):
            return False
        if await self._runtime.operational_failure(candidate_id) is not None:
            await self._terminate(candidate_id, CandidateLifecycle.STALE)
            return False
        candidate = await self._runtime.queue_for_generation(candidate_id, generation)
        if candidate is None:
            return False
        accepted, suppressed = self._queue.enqueue_with_suppressed(
            candidate_id, generation, foreground=foreground
        )
        if not accepted:
            await self._terminate(candidate_id, CandidateLifecycle.SUPERSEDED)
            return False
        if suppressed is not None:
            await self._terminate(suppressed.candidate_id, CandidateLifecycle.SUPERSEDED)
        return True

    async def pop_for_revalidation(self) -> PreparedSpeechCandidate | None:
        while (entry := self._queue.pop()) is not None:
            if await self._runtime.operational_failure(entry.candidate_id) is not None:
                await self._terminate(entry.candidate_id, CandidateLifecycle.STALE)
                continue
            begun = await self._runtime.begin_revalidation(entry.candidate_id, entry.generation)
            if begun is not None:
                return begun
        return None

    async def complete_revalidation(
        self,
        candidate_id: str,
        *,
        passed: bool,
        failure: CandidateLifecycle | None = None,
    ) -> PreparedSpeechCandidate:
        generation = self._runtime.generation(candidate_id)
        if passed and await self._runtime.operational_failure(candidate_id) is not None:
            passed = False
            failure = CandidateLifecycle.STALE
        if not passed:
            if failure is None:
                raise ValueError("revalidation failure lifecycle が必要です")
            await self._discarder.discard_current(
                candidate_id,
                generation,
                self._discard_reason(failure),
            )
            if not await self._runtime.is_current_generation(candidate_id, generation):
                raise ValueError("revalidation generation が更新されました")
        completed = await self._runtime.complete_revalidation(
            candidate_id, generation, passed, failure
        )
        if completed is None:
            raise ValueError("revalidation generation が更新されました")
        return completed

    def shutdown(self) -> tuple[PreparedSpeechQueueEntry, ...]:
        return self._queue.drain()

    async def _terminate(self, candidate_id: str, lifecycle: CandidateLifecycle) -> None:
        generation = self._runtime.generation(candidate_id)
        await self._discarder.discard_current(
            candidate_id, generation, self._discard_reason(lifecycle)
        )
        await self._runtime.cancel(candidate_id, lifecycle, expected_generation=generation)

    @staticmethod
    def _discard_reason(lifecycle: CandidateLifecycle) -> PreparedAudioDiscardReason:
        return {
            CandidateLifecycle.CANCELLED: PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
            CandidateLifecycle.STALE: PreparedAudioDiscardReason.CANDIDATE_STALE,
            CandidateLifecycle.SUPERSEDED: PreparedAudioDiscardReason.CANDIDATE_SUPERSEDED,
            CandidateLifecycle.FAILED: PreparedAudioDiscardReason.VERIFIER_FAILED,
        }[lifecycle]
