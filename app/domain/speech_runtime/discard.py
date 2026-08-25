from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .contracts import AudioReadinessState, SpeechComponentReadiness
from .runtime import SpeechRuntime


class PreparedAudioDiscardReason(str, Enum):
    SEMANTIC_REJECTED = "semantic_rejected"
    CHARACTER_REPAIRED = "character_repaired"
    VERIFIER_FAILED = "verifier_failed"
    PERFORMANCE_REBOUND = "performance_rebound"
    CANDIDATE_STALE = "candidate_stale"
    CANDIDATE_SUPERSEDED = "candidate_superseded"
    CANDIDATE_CANCELLED = "candidate_cancelled"


@dataclass(frozen=True, slots=True)
class PreparedAudioDiscardRequest:
    candidate_id: str
    utterance_id: str
    performance_plan_id: str
    audio_ref: str
    reason: PreparedAudioDiscardReason


class PreparedAudioDiscardPort(Protocol):
    async def discard(self, request: PreparedAudioDiscardRequest) -> None: ...


class PreparedAudioDiscarder:
    """#358 resource ownerへ候補局所artifactのdiscardだけを依頼する。"""

    def __init__(self, runtime: SpeechRuntime, port: PreparedAudioDiscardPort) -> None:
        self._runtime = runtime
        self._port = port

    async def discard_current(
        self, candidate_id: str, generation: int, reason: PreparedAudioDiscardReason
    ) -> bool:
        candidate = await self._runtime.candidate(candidate_id)
        if (
            not await self._runtime.is_current_generation(candidate_id, generation)
            or candidate.utterance_id is None
            or candidate.performance_plan_id is None
            or candidate.prepared_audio_ref is None
        ):
            return False
        request = PreparedAudioDiscardRequest(
            candidate_id,
            candidate.utterance_id,
            candidate.performance_plan_id,
            candidate.prepared_audio_ref,
            reason,
        )
        await self._port.discard(request)
        current = await self._runtime.candidate(candidate_id)
        if not await self._runtime.is_current_generation(candidate_id, generation):
            return False
        if current.prepared_audio_ref != request.audio_ref:
            return False
        await self._runtime.commit_generation_result(
            candidate_id,
            generation,
            readiness=SpeechComponentReadiness(
                current.readiness.semantics,
                current.readiness.character,
                current.readiness.verifier,
                current.readiness.performance,
                AudioReadinessState.DISCARDED,
            ),
            clear_prepared_audio=True,
        )
        return True
