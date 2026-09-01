from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.contracts.common import require_aware, require_identifier, utc_instant

from .contracts import CandidateLifecycle, PreparedSpeechCandidate
from .discard import PreparedAudioDiscarder, PreparedAudioDiscardReason
from .policy import (
    SpeechCandidatePriority,
    SpeechQueueOverflowPolicy,
    SpeechRuntimeOperationalPolicy,
)
from .runtime import SpeechRuntime


@dataclass(frozen=True, slots=True)
class PreparedSpeechQueueEntry:
    candidate_id: str
    generation: int
    priority: SpeechCandidatePriority
    prepared_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.candidate_id, "candidate_id")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("queue generation が不正です")
        if not isinstance(self.priority, SpeechCandidatePriority):
            raise ValueError("queue priority が不正です")
        require_aware(self.prepared_at, "prepared_at")


@dataclass(frozen=True, slots=True)
class SpeechQueueAdmissionResult:
    admitted_candidate_id: str | None = None
    rejected_candidate_id: str | None = None
    evicted_candidate_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "admitted_candidate_id",
            "rejected_candidate_id",
            "evicted_candidate_id",
        ):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        if (self.admitted_candidate_id is None) == (self.rejected_candidate_id is None):
            raise ValueError("admission resultはadmit/rejectのどちらか一方が必要です")
        if self.rejected_candidate_id is not None and self.evicted_candidate_id is not None:
            raise ValueError("reject時にevictionは記録できません")

    @property
    def admitted(self) -> bool:
        return self.admitted_candidate_id is not None


class PreparedSpeechQueue:
    """D10 canonical order / overflow policyを実装するbounded prepared queue。"""

    def __init__(self, policy: SpeechRuntimeOperationalPolicy) -> None:
        if not isinstance(policy, SpeechRuntimeOperationalPolicy):
            raise ValueError("Speech Runtime operational policy が必要です")
        self._policy = policy
        self._entries: dict[str, PreparedSpeechQueueEntry] = {}

    @property
    def policy(self) -> SpeechRuntimeOperationalPolicy:
        return self._policy

    def __len__(self) -> int:
        return len(self._entries)

    def enqueue(self, entry: PreparedSpeechQueueEntry) -> SpeechQueueAdmissionResult:
        if not isinstance(entry, PreparedSpeechQueueEntry):
            raise ValueError("queue entry が不正です")
        if entry.candidate_id in self._entries:
            return SpeechQueueAdmissionResult(rejected_candidate_id=entry.candidate_id)
        if len(self) < self._policy.prepared_queue_capacity:
            self._entries[entry.candidate_id] = entry
            return SpeechQueueAdmissionResult(admitted_candidate_id=entry.candidate_id)
        if self._policy.queue_overflow_policy is SpeechQueueOverflowPolicy.REJECT_NEW:
            return SpeechQueueAdmissionResult(rejected_candidate_id=entry.candidate_id)
        eviction = self._eviction_candidate()
        if entry.priority.rank < eviction.priority.rank:
            return SpeechQueueAdmissionResult(rejected_candidate_id=entry.candidate_id)
        del self._entries[eviction.candidate_id]
        self._entries[entry.candidate_id] = entry
        return SpeechQueueAdmissionResult(
            admitted_candidate_id=entry.candidate_id,
            evicted_candidate_id=eviction.candidate_id,
        )

    def contains(self, candidate_id: str) -> bool:
        return candidate_id in self._entries

    def pop(self) -> PreparedSpeechQueueEntry | None:
        if not self._entries:
            return None
        entry = min(self._entries.values(), key=self._presentation_order_key)
        del self._entries[entry.candidate_id]
        return entry

    def remove(self, candidate_id: str) -> None:
        self._entries.pop(candidate_id, None)

    def drain(self) -> tuple[PreparedSpeechQueueEntry, ...]:
        entries = tuple(sorted(self._entries.values(), key=self._presentation_order_key))
        self._entries.clear()
        return entries

    def _eviction_candidate(self) -> PreparedSpeechQueueEntry:
        minimum_rank = min(entry.priority.rank for entry in self._entries.values())
        lowest = tuple(
            entry for entry in self._entries.values() if entry.priority.rank == minimum_rank
        )
        return min(lowest, key=self._oldest_key)

    @staticmethod
    def _presentation_order_key(entry: PreparedSpeechQueueEntry) -> tuple[object, ...]:
        return (-entry.priority.rank, utc_instant(entry.prepared_at), entry.candidate_id)

    @staticmethod
    def _oldest_key(entry: PreparedSpeechQueueEntry) -> tuple[object, ...]:
        return (utc_instant(entry.prepared_at), entry.candidate_id)


class PreparedSpeechQueueCoordinator:
    """generation/policy/expiry fence後のcandidateだけをprepared queueへ進める。"""

    def __init__(
        self,
        runtime: SpeechRuntime,
        queue: PreparedSpeechQueue,
        discarder: PreparedAudioDiscarder,
    ) -> None:
        if not runtime.operational_policy.same_generation(
            queue.policy.policy_id,
            queue.policy.policy_revision,
        ):
            raise ValueError("runtimeとqueueのoperational policy generationが一致しません")
        self._runtime = runtime
        self._queue = queue
        self._discarder = discarder

    def __len__(self) -> int:
        return len(self._queue)

    async def enqueue_current(
        self,
        candidate_id: str,
        generation: int,
    ) -> SpeechQueueAdmissionResult:
        if self._queue.contains(candidate_id):
            return SpeechQueueAdmissionResult(rejected_candidate_id=candidate_id)
        if await self._runtime.operational_failure(candidate_id) is not None:
            await self._terminate(candidate_id, CandidateLifecycle.STALE)
            return SpeechQueueAdmissionResult(rejected_candidate_id=candidate_id)
        candidate = await self._runtime.queue_for_generation(candidate_id, generation)
        if candidate is None:
            if await self._runtime.operational_failure(candidate_id) is not None:
                await self._terminate(candidate_id, CandidateLifecycle.STALE)
            return SpeechQueueAdmissionResult(rejected_candidate_id=candidate_id)
        if candidate.prepared_at is None:
            await self._terminate(candidate_id, CandidateLifecycle.FAILED)
            raise ValueError("prepared queueにはprepared_atが必要です")
        result = self._queue.enqueue(
            PreparedSpeechQueueEntry(
                candidate_id=candidate.candidate_id,
                generation=generation,
                priority=candidate.priority,
                prepared_at=candidate.prepared_at,
            )
        )
        if not result.admitted:
            await self._terminate(candidate_id, CandidateLifecycle.SUPERSEDED)
            return result
        if result.evicted_candidate_id is not None:
            await self._terminate(result.evicted_candidate_id, CandidateLifecycle.SUPERSEDED)
        return result

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
            candidate_id,
            generation,
            passed,
            failure,
        )
        if completed is None:
            raise ValueError("revalidation generation が更新されました")
        return completed

    def shutdown(self) -> tuple[PreparedSpeechQueueEntry, ...]:
        return self._queue.drain()

    async def _terminate(self, candidate_id: str, lifecycle: CandidateLifecycle) -> None:
        generation = self._runtime.generation(candidate_id)
        await self._discarder.discard_current(
            candidate_id,
            generation,
            self._discard_reason(lifecycle),
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
