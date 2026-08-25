from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
    SpeechPresentationMode,
    SpeechReadinessState,
    VerifierReadinessState,
)
from app.domain.speech_runtime.discard import (
    PreparedAudioDiscarder,
    PreparedAudioDiscardPort,
    PreparedAudioDiscardReason,
    PreparedAudioDiscardRequest,
)
from app.domain.speech_runtime.lifecycle import SpeechCandidateLifecycleExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime


class _FakeResourceOwner(PreparedAudioDiscardPort):
    def __init__(self, *resources: str) -> None:
        self.resources = set(resources or ("audio-g1",))

    def resolve(self, audio_ref: str) -> str | None:
        return audio_ref if audio_ref in self.resources else None

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        self.resources.discard(request.audio_ref)


class _BlockingOwner(_FakeResourceOwner):
    def __init__(self) -> None:
        super().__init__("audio-g1", "audio-g2")
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        self.entered.set()
        await self.release.wait()
        await super().discard(request)


async def _advance_to_generation_two(runtime: SpeechRuntime) -> None:
    await runtime.supersede_generation("candidate")
    await runtime.commit_generation_result(
        "candidate",
        2,
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.NOT_REQUESTED,
        ),
        utterance_id="utterance-g2",
        performance_plan_id="performance-g2",
        semantic_acceptance_id="acceptance-g2",
    )


def _candidate() -> PreparedSpeechCandidate:
    now = datetime.now(timezone.utc)
    return PreparedSpeechCandidate(
        candidate_id="candidate",
        preparation_id="preparation",
        source_decision_id="decision",
        source_event_ids=("event",),
        speech_plan_id="plan",
        utterance_id="utterance",
        performance_plan_id="performance-g1",
        source_context_revision=1,
        goal_revision=1,
        attention_revision=1,
        priority=LLMPriority.FOREGROUND,
        interruptibility=LLMInterruptibility.INTERRUPTIBLE,
        expiry_policy_ref="expiry",
        required_preconditions=(),
        semantic_requirement=SemanticVerificationRequirement.REQUIRED,
        semantic_acceptance_id="acceptance",
        prepared_audio_ref="audio-g1",
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
        lifecycle=CandidateLifecycle.PREPARED,
        created_at=now,
        updated_at=now,
        expression_revision=1,
    )


@pytest.mark.asyncio
async def test_expression_only_rebind_preserves_utterance_semantics_and_rejects_old_results() -> (
    None
):
    runtime = SpeechRuntime()
    await runtime.register(_candidate())
    owner = _FakeResourceOwner()
    generation = await SpeechCandidateLifecycleExecutor(
        runtime, PreparedAudioDiscarder(runtime, owner)
    ).rebind_performance("candidate", 2)
    rebound = await runtime.candidate("candidate")
    assert generation == 2
    assert rebound.utterance_id == "utterance"
    assert rebound.speech_plan_id == "plan"
    assert rebound.semantic_acceptance_id == "acceptance"
    assert rebound.repair_count == 0
    assert rebound.performance_plan_id is None
    assert rebound.prepared_audio_ref is None
    assert rebound.performance_generation == 2
    assert rebound.expression_revision == 2
    late = await runtime.commit_generation_result(
        "candidate",
        1,
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
        performance_plan_id="late-performance",
        prepared_audio_ref="late-audio",
    )
    assert late is None
    current = await runtime.candidate("candidate")
    assert current.performance_plan_id is None
    assert current.prepared_audio_ref is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [CandidateLifecycle.STALE, CandidateLifecycle.SUPERSEDED, CandidateLifecycle.CANCELLED],
)
async def test_discard_port_invalidates_actual_audio_before_terminal_transition(
    operation: CandidateLifecycle,
) -> None:
    runtime = SpeechRuntime()
    await runtime.register(_candidate())
    owner = _FakeResourceOwner()
    executor = SpeechCandidateLifecycleExecutor(runtime, PreparedAudioDiscarder(runtime, owner))
    assert owner.resolve("audio-g1") is not None
    await executor.terminate("candidate", operation)
    assert (await runtime.candidate("candidate")).prepared_audio_ref is None
    assert owner.resolve("audio-g1") is None


@pytest.mark.asyncio
async def test_expression_rebind_discards_old_resource_and_preserves_semantics() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_candidate())
    owner = _FakeResourceOwner()
    executor = SpeechCandidateLifecycleExecutor(runtime, PreparedAudioDiscarder(runtime, owner))
    await executor.rebind_performance("candidate", 2)
    current = await runtime.candidate("candidate")
    assert current.utterance_id == "utterance"
    assert current.speech_plan_id == "plan"
    assert current.semantic_acceptance_id == "acceptance"
    assert current.repair_count == 0
    assert current.prepared_audio_ref is None
    assert owner.resolve("audio-g1") is None


@pytest.mark.asyncio
async def test_discard_wait_race_never_restores_or_discards_g2_audio() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_candidate())
    owner = _BlockingOwner()
    discarder = PreparedAudioDiscarder(runtime, owner)
    discard_task = asyncio.create_task(
        discarder.discard_current("candidate", 1, PreparedAudioDiscardReason.PERFORMANCE_REBOUND)
    )
    await owner.entered.wait()
    await runtime.supersede_generation("candidate")
    await runtime.commit_generation_result(
        "candidate",
        2,
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
        utterance_id="utterance-g2",
        performance_plan_id="performance-g2",
        semantic_acceptance_id="acceptance-g2",
        prepared_audio_ref="audio-g2",
    )
    late = await runtime.commit_generation_result(
        "candidate",
        1,
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
        prepared_audio_ref="audio-g1",
    )
    owner.release.set()
    await discard_task
    current = await runtime.candidate("candidate")
    assert late is None
    assert runtime.generation("candidate") == 2
    assert current.prepared_audio_ref == "audio-g2"
    assert owner.resolve("audio-g1") is None
    assert owner.resolve("audio-g2") == "audio-g2"


@pytest.mark.asyncio
async def test_stale_expression_rebind_cannot_mutate_generation_two_after_discard() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_candidate())
    owner = _BlockingOwner()
    executor = SpeechCandidateLifecycleExecutor(runtime, PreparedAudioDiscarder(runtime, owner))
    stale_rebind = asyncio.create_task(executor.rebind_performance("candidate", 2))
    await owner.entered.wait()
    await _advance_to_generation_two(runtime)
    owner.release.set()
    assert await stale_rebind is None
    current = await runtime.candidate("candidate")
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.PREPARED
    assert current.performance_plan_id == "performance-g2"


@pytest.mark.asyncio
async def test_stale_terminate_cannot_cancel_generation_two_after_discard() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_candidate())
    owner = _BlockingOwner()
    executor = SpeechCandidateLifecycleExecutor(runtime, PreparedAudioDiscarder(runtime, owner))
    stale_terminate = asyncio.create_task(
        executor.terminate("candidate", CandidateLifecycle.STALE)
    )
    await owner.entered.wait()
    await _advance_to_generation_two(runtime)
    owner.release.set()
    assert await stale_terminate is None
    current = await runtime.candidate("candidate")
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.PREPARED
