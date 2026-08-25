from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticRepairAttempt,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
    SpeechPresentationMode,
    SpeechReadinessState,
    VerifierReadinessState,
)
from app.domain.speech_runtime.discard import (
    PreparedAudioDiscarder,
    PreparedAudioDiscardPort,
    PreparedAudioDiscardRequest,
)
from app.domain.speech_runtime.repair import (
    SemanticRepairEvidence,
    SpeechSemanticRepairExecutor,
)
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskKey, CandidateTaskRegistry


class _FakeOwner(PreparedAudioDiscardPort):
    def __init__(self, *refs: str) -> None:
        self.refs = set(refs)
        self.requests: list[PreparedAudioDiscardRequest] = []

    def resolve(self, ref: str) -> str | None:
        return ref if ref in self.refs else None

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        self.requests.append(request)
        self.refs.discard(request.audio_ref)


class _PostDiscardSupersedeRaceRuntime(SpeechRuntime):
    """G1 repairのsupersede mutation直前に別owner結果でG2を確立する。"""

    def __init__(self) -> None:
        super().__init__()
        self.inject_race = False

    async def supersede_generation(
        self, candidate_id: str, expected_generation: int
    ) -> int | None:
        if self.inject_race:
            self.inject_race = False
            generation_two = await super().supersede_generation(
                candidate_id, expected_generation
            )
            assert generation_two == 2
            await self.commit_generation_result(
                candidate_id,
                generation_two,
                readiness=_ready(verifier=VerifierReadinessState.ACCEPTED),
                utterance_id="utterance-g2",
                performance_plan_id="performance-g2",
                semantic_acceptance_id="acceptance-g2",
            )
        return await super().supersede_generation(candidate_id, expected_generation)


def _candidate(candidate_id: str = "candidate") -> PreparedSpeechCandidate:
    now = datetime.now(timezone.utc)
    return PreparedSpeechCandidate(
        candidate_id=candidate_id,
        preparation_id=f"preparation-{candidate_id}",
        source_decision_id="decision",
        source_event_ids=("event",),
        speech_plan_id="speech-plan",
        utterance_id="utterance-g1",
        performance_plan_id=None,
        source_context_revision=1,
        goal_revision=1,
        attention_revision=1,
        priority=LLMPriority.FOREGROUND,
        interruptibility=LLMInterruptibility.INTERRUPTIBLE,
        expiry_policy_ref="expiry",
        required_preconditions=(),
        semantic_requirement=SemanticVerificationRequirement.REQUIRED,
        semantic_acceptance_id=None,
        prepared_audio_ref=None,
        presentation_modes=(SpeechPresentationMode.TEXT_ONLY,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.PENDING,
            SpeechReadinessState.READY,
            AudioReadinessState.NOT_REQUESTED,
        ),
        lifecycle=CandidateLifecycle.PREPARING,
        created_at=now,
        updated_at=now,
    )


def _ready(
    *,
    verifier: VerifierReadinessState = VerifierReadinessState.PENDING,
    audio: AudioReadinessState = AudioReadinessState.NOT_REQUESTED,
) -> SpeechComponentReadiness:
    return SpeechComponentReadiness(
        SpeechReadinessState.READY,
        SpeechReadinessState.READY,
        verifier,
        SpeechReadinessState.READY,
        audio,
    )


async def _repair(_: object) -> None:
    return None


def _executor(runtime: SpeechRuntime, tasks: CandidateTaskRegistry) -> SpeechSemanticRepairExecutor:
    return SpeechSemanticRepairExecutor(
        runtime, tasks, PreparedAudioDiscarder(runtime, _FakeOwner())
    )


@pytest.mark.asyncio
async def test_first_reject_repairs_once_with_empty_priors_and_same_plan() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    executor = _executor(runtime, tasks)
    received: list[SemanticRepairAttempt] = []

    async def repair(attempt: SemanticRepairAttempt) -> None:
        received.append(attempt)

    result = await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",)),
        repair_character=repair,
    )
    current = await runtime.candidate("candidate")
    assert result is not None and result.value == "repair_once"
    assert runtime.generation("candidate") == 2
    assert current.speech_plan_id == "speech-plan"
    assert len(received) == 1
    assert received[0].prior_realizations == ()


@pytest.mark.asyncio
async def test_second_reject_is_final_and_never_calls_third_character() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    executor = _executor(runtime, tasks)
    calls = 0

    async def repair(_: object) -> None:
        nonlocal calls
        calls += 1

    evidence = SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",))
    await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=evidence,
        repair_character=repair,
    )
    await runtime.commit_generation_result(
        "candidate", 2, readiness=_ready(), utterance_id="utterance-g2"
    )
    result = await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=2,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=evidence,
        repair_character=repair,
    )
    assert result is not None and result.value == "rejected_final"
    assert calls == 1
    assert runtime.generation("candidate") == 2
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.REJECTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed,stale,expected",
    [(True, False, "verifier_failed"), (False, True, "replan_required")],
)
async def test_verifier_failure_or_stale_plan_never_repairs(
    failed: bool, stale: bool, expected: str
) -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    calls = 0

    async def repair(_: object) -> None:
        nonlocal calls
        calls += 1

    result = await _executor(runtime, tasks).handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=None,
        semantic_acceptance_id=None,
        verifier_execution_failed=failed,
        speech_plan_stale=stale,
        evidence=None,
        repair_character=repair,
    )
    assert result is not None and result.value == expected
    assert calls == 0
    assert runtime.generation("candidate") == 1


@pytest.mark.asyncio
async def test_old_generation_performance_tts_and_verifier_cannot_overwrite_g2() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    executor = _executor(runtime, tasks)
    evidence = SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",))
    await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=evidence,
        repair_character=_repair,
    )
    await runtime.commit_generation_result(
        "candidate",
        2,
        readiness=_ready(verifier=VerifierReadinessState.ACCEPTED, audio=AudioReadinessState.READY),
        utterance_id="utterance-g2",
        performance_plan_id="performance-g2",
        semantic_acceptance_id="acceptance-g2",
        prepared_audio_ref="audio-g2",
    )
    late = await runtime.commit_generation_result(
        "candidate",
        1,
        readiness=_ready(verifier=VerifierReadinessState.ACCEPTED, audio=AudioReadinessState.READY),
        performance_plan_id="performance-g1",
        semantic_acceptance_id="acceptance-g1",
        prepared_audio_ref="audio-g1",
    )
    current = await runtime.candidate("candidate")
    assert late is None
    assert runtime.generation("candidate") == 2
    assert current.performance_plan_id == "performance-g2"
    assert current.prepared_audio_ref == "audio-g2"
    assert current.semantic_acceptance_id == "acceptance-g2"


@pytest.mark.asyncio
async def test_speculative_g1_artifact_is_discarded_before_repair_g2() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    await runtime.commit_generation_result(
        "candidate",
        1,
        readiness=_ready(audio=AudioReadinessState.READY),
        performance_plan_id="performance-g1",
        prepared_audio_ref="speculative-audio-g1",
    )
    await _executor(runtime, tasks).handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",)),
        repair_character=_repair,
    )
    current = await runtime.candidate("candidate")
    assert current.prepared_audio_ref is None
    assert current.readiness.audio is AudioReadinessState.NOT_REQUESTED
    assert current.lifecycle is CandidateLifecycle.PREPARING


@pytest.mark.asyncio
async def test_late_g1_verifier_result_does_not_restore_presentation_eligibility() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    executor = _executor(runtime, tasks)
    evidence = SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",))
    await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=evidence,
        repair_character=_repair,
    )
    late = await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=True,
        semantic_acceptance_id="late-acceptance",
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=None,
        repair_character=_repair,
    )
    current = await runtime.candidate("candidate")
    assert late is None
    assert current.semantic_acceptance_id is None
    assert current.lifecycle is CandidateLifecycle.PREPARING


@pytest.mark.asyncio
async def test_stale_g1_repair_cannot_supersede_or_cancel_generation_two() -> None:
    runtime = _PostDiscardSupersedeRaceRuntime()
    tasks = CandidateTaskRegistry()
    await runtime.register(_candidate())
    release = asyncio.Event()

    async def g2_work() -> object:
        await release.wait()
        return object()

    task_g2 = tasks.start(CandidateTaskKey("candidate", 2, "performance"), g2_work())
    runtime.inject_race = True
    result = await _executor(runtime, tasks).handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",)),
        repair_character=_repair,
    )
    current = await runtime.candidate("candidate")
    assert result is None
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.PREPARED
    assert current.utterance_id == "utterance-g2"
    assert current.performance_plan_id == "performance-g2"
    assert not task_g2.done()
    release.set()
    await task_g2


@pytest.mark.asyncio
async def test_repair_cancels_only_old_generation_and_other_candidate_continues() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate("candidate-a"))
    await runtime.register(_candidate("candidate-b"))
    entered_a, entered_b, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocked(entered: asyncio.Event) -> object:
        entered.set()
        await release.wait()
        return object()

    task_a = tasks.start(CandidateTaskKey("candidate-a", 1, "performance"), blocked(entered_a))
    task_b = tasks.start(CandidateTaskKey("candidate-b", 1, "performance"), blocked(entered_b))
    await entered_a.wait()
    await entered_b.wait()
    await _executor(runtime, tasks).handle_verifier_result(
        candidate_id="candidate-a",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",)),
        repair_character=_repair,
    )
    assert task_a.cancelled()
    assert not task_b.done()
    release.set()
    await task_b


@pytest.mark.asyncio
async def test_only_accepted_utterance_enters_prior_pool() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    executor = _executor(runtime, tasks)
    await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",)),
        repair_character=_repair,
    )
    assert executor.accepted_priors == ()
    await runtime.commit_generation_result(
        "candidate", 2, readiness=_ready(), utterance_id="utterance-g2"
    )
    await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=2,
        semantic_accepted=True,
        semantic_acceptance_id="acceptance-g2",
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=None,
        repair_character=_repair,
    )
    assert tuple(executor.accepted_priors) == ("utterance-g2",)


@pytest.mark.asyncio
async def test_repair_discards_actual_g1_resource_before_starting_g2() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    await runtime.commit_generation_result(
        "candidate",
        1,
        readiness=_ready(audio=AudioReadinessState.READY),
        performance_plan_id="performance-g1",
        prepared_audio_ref="audio-g1",
    )
    owner = _FakeOwner("audio-g1")
    executor = SpeechSemanticRepairExecutor(runtime, tasks, PreparedAudioDiscarder(runtime, owner))
    attempts: list[SemanticRepairAttempt] = []

    async def repair(attempt: SemanticRepairAttempt) -> None:
        attempts.append(attempt)

    await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",)),
        repair_character=repair,
    )
    current = await runtime.candidate("candidate")
    assert current.prepared_audio_ref is None
    assert runtime.generation("candidate") == 2
    assert owner.resolve("audio-g1") is None
    assert len(owner.requests) == 1
    assert attempts[0].speech_plan_id == "speech-plan"
    assert attempts[0].prior_realizations == ()


@pytest.mark.asyncio
async def test_second_reject_discards_actual_g2_resource_without_third_generation() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_candidate())
    owner = _FakeOwner("audio-g2")
    executor = SpeechSemanticRepairExecutor(runtime, tasks, PreparedAudioDiscarder(runtime, owner))
    evidence = SemanticRepairEvidence(("meaning_mismatch",), ("evidence-1",))
    await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=evidence,
        repair_character=_repair,
    )
    await runtime.commit_generation_result(
        "candidate",
        2,
        readiness=_ready(audio=AudioReadinessState.READY),
        utterance_id="utterance-g2",
        performance_plan_id="performance-g2",
        prepared_audio_ref="audio-g2",
    )
    result = await executor.handle_verifier_result(
        candidate_id="candidate",
        generation=2,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=evidence,
        repair_character=_repair,
    )
    current = await runtime.candidate("candidate")
    assert result is not None and result.value == "rejected_final"
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.REJECTED
    assert current.prepared_audio_ref is None
    assert owner.resolve("audio-g2") is None
    assert len(owner.requests) == 1
