from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    SemanticRepairAttempt,
    SemanticRepairDisposition,
    SpeechComponentReadiness,
    VerifierReadinessState,
)
from .runtime import SpeechRuntime
from .tasks import CandidateTaskRegistry


@dataclass(frozen=True, slots=True)
class SemanticRepairEvidence:
    """#363のtyped rejection evidenceだけをrepairへ渡す。"""

    rejection_categories: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("rejection_categories", "evidence_refs"):
            values = tuple(getattr(self, name))
            if not values or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"{name} が不正です")
            object.__setattr__(self, name, values)


CharacterRepairWork = Callable[[SemanticRepairAttempt], Awaitable[None]]


class SpeechSemanticRepairExecutor:
    """#363結果から最大一回だけ同一semantic planのCharacter repairを起動する。"""

    def __init__(self, runtime: SpeechRuntime, tasks: CandidateTaskRegistry) -> None:
        self._runtime = runtime
        self._tasks = tasks
        self._accepted_priors: list[str] = []

    @property
    def accepted_priors(self) -> tuple[str, ...]:
        return tuple(self._accepted_priors)

    async def handle_verifier_result(
        self,
        *,
        candidate_id: str,
        generation: int,
        semantic_accepted: bool | None,
        semantic_acceptance_id: str | None,
        verifier_execution_failed: bool,
        speech_plan_stale: bool,
        evidence: SemanticRepairEvidence | None,
        repair_character: CharacterRepairWork,
    ) -> SemanticRepairDisposition | None:
        """旧世代の遅延結果は何もcommitせずNoneで終了する。"""
        if not await self._runtime.is_current_generation(candidate_id, generation):
            return None
        disposition = semantic_repair_disposition(
            semantic_accepted=semantic_accepted,
            verifier_execution_failed=verifier_execution_failed,
            speech_plan_stale=speech_plan_stale,
            character_generation_count=generation,
        )
        candidate = await self._runtime.candidate(candidate_id)
        if disposition is SemanticRepairDisposition.ACCEPTED:
            if semantic_acceptance_id is None:
                raise ValueError("accepted verifier resultにはacceptance idが必要です")
            updated = await self._runtime.commit_generation_result(
                candidate_id,
                generation,
                readiness=SpeechComponentReadiness(
                    candidate.readiness.semantics,
                    candidate.readiness.character,
                    VerifierReadinessState.ACCEPTED,
                    candidate.readiness.performance,
                    candidate.readiness.audio,
                ),
                semantic_acceptance_id=semantic_acceptance_id,
            )
            if updated is not None and updated.utterance_id is not None:
                self._accepted_priors.append(updated.utterance_id)
            return disposition
        if disposition is SemanticRepairDisposition.REPAIR_ONCE:
            if evidence is None or candidate.utterance_id is None:
                raise ValueError("repairにはtyped evidenceとutteranceが必要です")
            next_generation = await self._runtime.supersede_generation(candidate_id)
            await self._tasks.cancel_candidate(candidate_id, before_generation=next_generation)
            attempt = SemanticRepairAttempt(
                attempt=1,
                maximum_attempts=1,
                speech_plan_id=candidate.speech_plan_id,
                utterance_id=candidate.utterance_id,
                rejection_categories=evidence.rejection_categories,
                evidence_refs=evidence.evidence_refs,
                prior_realizations=(),
            )
            await repair_character(attempt)
            return disposition
        if disposition is SemanticRepairDisposition.REJECTED_FINAL:
            await self._runtime.commit_generation_result(
                candidate_id,
                generation,
                readiness=SpeechComponentReadiness(
                    candidate.readiness.semantics,
                    candidate.readiness.character,
                    VerifierReadinessState.REJECTED,
                    candidate.readiness.performance,
                    AudioReadinessState.DISCARDED,
                ),
            )
            return disposition
        terminal = (
            CandidateLifecycle.STALE
            if disposition is SemanticRepairDisposition.REPLAN_REQUIRED
            else CandidateLifecycle.FAILED
        )
        await self._runtime.cancel(candidate_id, terminal)
        return disposition


def semantic_repair_disposition(
    *,
    semantic_accepted: bool | None,
    verifier_execution_failed: bool,
    speech_plan_stale: bool,
    character_generation_count: int,
) -> SemanticRepairDisposition:
    """#363のclosed結果だけで最大一回のCharacter repairを許可する。"""
    if type(character_generation_count) is not int or character_generation_count < 1:
        raise ValueError("character_generation_count が不正です")
    if speech_plan_stale:
        return SemanticRepairDisposition.REPLAN_REQUIRED
    if verifier_execution_failed or semantic_accepted is None:
        return SemanticRepairDisposition.VERIFIER_FAILED
    if semantic_accepted:
        return SemanticRepairDisposition.ACCEPTED
    if character_generation_count == 1:
        return SemanticRepairDisposition.REPAIR_ONCE
    return SemanticRepairDisposition.REJECTED_FINAL
