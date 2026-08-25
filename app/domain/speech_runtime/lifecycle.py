from __future__ import annotations

from .contracts import CandidateLifecycle
from .discard import PreparedAudioDiscarder, PreparedAudioDiscardReason
from .runtime import SpeechRuntime


class SpeechCandidateLifecycleExecutor:
    """audio discardを#358 portへ委譲してからcandidate局所遷移を行う。"""

    def __init__(self, runtime: SpeechRuntime, discarder: PreparedAudioDiscarder) -> None:
        self._runtime = runtime
        self._discarder = discarder

    async def rebind_performance(self, candidate_id: str, expression_revision: int) -> int | None:
        generation = self._runtime.generation(candidate_id)
        await self._discarder.discard_current(
            candidate_id, generation, PreparedAudioDiscardReason.PERFORMANCE_REBOUND
        )
        if not await self._runtime.is_current_generation(candidate_id, generation):
            return None
        return await self._runtime.rebind_performance_for_expression(
            candidate_id, expression_revision
        )

    async def terminate(
        self, candidate_id: str, lifecycle: CandidateLifecycle
    ) -> CandidateLifecycle | None:
        reasons = {
            CandidateLifecycle.STALE: PreparedAudioDiscardReason.CANDIDATE_STALE,
            CandidateLifecycle.SUPERSEDED: PreparedAudioDiscardReason.CANDIDATE_SUPERSEDED,
            CandidateLifecycle.CANCELLED: PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
        }
        if lifecycle not in reasons:
            raise ValueError("discard lifecycle が不正です")
        generation = self._runtime.generation(candidate_id)
        await self._discarder.discard_current(candidate_id, generation, reasons[lifecycle])
        if not await self._runtime.is_current_generation(candidate_id, generation):
            return None
        await self._runtime.cancel(candidate_id, lifecycle)
        return lifecycle
