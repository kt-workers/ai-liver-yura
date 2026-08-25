from __future__ import annotations

import asyncio
from dataclasses import replace
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
    PreparedAudioDiscardRequest,
)
from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueCoordinator
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.shutdown import SpeechRuntimeShutdown
from app.domain.speech_runtime.tasks import CandidateTaskKey, CandidateTaskRegistry


def _prepared(candidate_id: str, priority: LLMPriority) -> PreparedSpeechCandidate:
    now = datetime.now(timezone.utc)
    return PreparedSpeechCandidate(
        candidate_id=candidate_id,
        preparation_id=f"preparation-{candidate_id}",
        source_decision_id="decision",
        source_event_ids=("event",),
        speech_plan_id=f"plan-{candidate_id}",
        utterance_id=f"utterance-{candidate_id}",
        performance_plan_id=f"performance-{candidate_id}",
        source_context_revision=1,
        goal_revision=None,
        attention_revision=None,
        priority=priority,
        interruptibility=LLMInterruptibility.INTERRUPTIBLE,
        expiry_policy_ref="expiry",
        required_preconditions=(),
        semantic_requirement=SemanticVerificationRequirement.REQUIRED,
        semantic_acceptance_id=f"acceptance-{candidate_id}",
        prepared_audio_ref=None,
        presentation_modes=(SpeechPresentationMode.TEXT_ONLY,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.NOT_REQUESTED,
        ),
        lifecycle=CandidateLifecycle.PREPARED,
        created_at=now,
        updated_at=now,
    )


class _DiscardOwner(PreparedAudioDiscardPort):
    def __init__(self, *refs: str) -> None:
        self.refs = set(refs)
        self.requests: list[PreparedAudioDiscardRequest] = []

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        self.requests.append(request)
        self.refs.discard(request.audio_ref)


class _BlockingDiscardOwner(_DiscardOwner):
    def __init__(self, *refs: str) -> None:
        super().__init__(*refs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        self.entered.set()
        await self.release.wait()
        await super().discard(request)


class _PostCheckGenerationRaceRuntime(SpeechRuntime):
    """queueの外部generation確認後、runtime mutation直前にG2を作る。"""

    def __init__(self) -> None:
        super().__init__()
        self.inject_race = False

    async def complete_revalidation(
        self,
        candidate_id: str,
        expected_generation: int,
        passed: bool,
        failure: CandidateLifecycle | None = None,
    ) -> PreparedSpeechCandidate | None:
        if self.inject_race:
            self.inject_race = False
            await self.supersede_generation(candidate_id)
            await self.commit_generation_result(
                candidate_id,
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
            await self.queue_for_generation(candidate_id, 2)
            await self.begin_revalidation(candidate_id)
        return await super().complete_revalidation(
            candidate_id, expected_generation, passed, failure
        )


def _coordinator(
    runtime: SpeechRuntime, queue: PreparedSpeechQueue, owner: _DiscardOwner | None = None
) -> PreparedSpeechQueueCoordinator:
    return PreparedSpeechQueueCoordinator(
        runtime, queue, PreparedAudioDiscarder(runtime, owner or _DiscardOwner())
    )


@pytest.mark.asyncio
async def test_only_current_generation_can_enqueue_and_duplicate_is_rejected() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_prepared("candidate", LLMPriority.FOREGROUND))
    coordinator = _coordinator(runtime, PreparedSpeechQueue(2))
    await runtime.supersede_generation("candidate")
    assert not await coordinator.enqueue_current("candidate", 1, foreground=True)
    # G2が再びPREPAREDへ収束した後だけqueueへ入れられる。
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
    assert await coordinator.enqueue_current("candidate", 2, foreground=True)
    assert not await coordinator.enqueue_current("candidate", 2, foreground=True)


@pytest.mark.asyncio
async def test_foreground_suppression_closes_displaced_background_candidate() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_prepared("background", LLMPriority.BACKGROUND))
    await runtime.register(_prepared("foreground", LLMPriority.FOREGROUND))
    coordinator = _coordinator(runtime, PreparedSpeechQueue(1))
    assert await coordinator.enqueue_current("background", 1, foreground=False)
    assert await coordinator.enqueue_current("foreground", 1, foreground=True)
    assert (await runtime.candidate("background")).lifecycle is CandidateLifecycle.SUPERSEDED
    next_candidate = await coordinator.pop_for_revalidation()
    assert next_candidate is not None and next_candidate.candidate_id == "foreground"
    ready = await coordinator.complete_revalidation("foreground", passed=True)
    assert ready.lifecycle is CandidateLifecycle.READY_TO_PRESENT


@pytest.mark.asyncio
async def test_shutdown_cancels_candidate_local_tasks_and_drains_queue() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_prepared("candidate-a", LLMPriority.FOREGROUND))
    await runtime.register(_prepared("candidate-b", LLMPriority.BACKGROUND))
    queue = _coordinator(runtime, PreparedSpeechQueue(2))
    await queue.enqueue_current("candidate-a", 1, foreground=True)
    await queue.enqueue_current("candidate-b", 1, foreground=False)
    tasks = CandidateTaskRegistry()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def pending() -> object:
        entered.set()
        await release.wait()
        return object()

    task = tasks.start(CandidateTaskKey("candidate-a", 1, "tts"), pending())
    await entered.wait()
    closed = await SpeechRuntimeShutdown(
        runtime, tasks, queue, PreparedAudioDiscarder(runtime, _DiscardOwner())
    ).close()
    assert set(closed) == {"candidate-a", "candidate-b"}
    assert task.cancelled()
    assert tasks.pending_task_count == 0
    assert len(queue) == 0
    assert (await runtime.candidate("candidate-a")).lifecycle is CandidateLifecycle.CANCELLED


@pytest.mark.asyncio
async def test_shutdown_discards_bound_audio_resource_before_terminal_transition() -> None:
    runtime = SpeechRuntime()
    candidate = _prepared("candidate", LLMPriority.FOREGROUND)
    candidate = replace(
        candidate,
        prepared_audio_ref="audio-candidate",
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
    )
    await runtime.register(candidate)
    owner = _DiscardOwner("audio-candidate")
    coordinator = _coordinator(runtime, PreparedSpeechQueue(1), owner)
    closed = await SpeechRuntimeShutdown(
        runtime, CandidateTaskRegistry(), coordinator, PreparedAudioDiscarder(runtime, owner)
    ).close()
    assert closed == ("candidate",)
    assert not owner.refs
    assert owner.requests[0].audio_ref == "audio-candidate"
    assert (await runtime.candidate("candidate")).prepared_audio_ref is None


@pytest.mark.asyncio
async def test_queue_suppression_discards_displaced_audio_resource() -> None:
    runtime = SpeechRuntime()
    background = replace(
        _prepared("background", LLMPriority.BACKGROUND),
        prepared_audio_ref="audio-background",
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
    )
    await runtime.register(background)
    await runtime.register(_prepared("foreground", LLMPriority.FOREGROUND))
    owner = _DiscardOwner("audio-background")
    coordinator = _coordinator(runtime, PreparedSpeechQueue(1), owner)
    assert await coordinator.enqueue_current("background", 1, foreground=False)
    assert await coordinator.enqueue_current("foreground", 1, foreground=True)
    assert owner.requests[0].audio_ref == "audio-background"
    assert not owner.refs
    displaced = await runtime.candidate("background")
    assert displaced.lifecycle is CandidateLifecycle.SUPERSEDED
    assert displaced.prepared_audio_ref is None


@pytest.mark.asyncio
async def test_old_revalidation_failure_cannot_terminalize_new_generation_after_slow_discard(
) -> None:
    runtime = SpeechRuntime()
    candidate = replace(
        _prepared("candidate", LLMPriority.FOREGROUND),
        prepared_audio_ref="audio-g1",
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
    )
    await runtime.register(candidate)
    owner = _BlockingDiscardOwner("audio-g1", "audio-g2")
    coordinator = _coordinator(runtime, PreparedSpeechQueue(2), owner)
    assert await coordinator.enqueue_current("candidate", 1, foreground=True)
    assert (await coordinator.pop_for_revalidation()) is not None
    stale_g1 = asyncio.create_task(
        coordinator.complete_revalidation(
            "candidate", passed=False, failure=CandidateLifecycle.STALE
        )
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
    assert await coordinator.enqueue_current("candidate", 2, foreground=True)
    assert (await coordinator.pop_for_revalidation()) is not None
    owner.release.set()
    with pytest.raises(ValueError, match="generation"):
        await stale_g1
    current = await runtime.candidate("candidate")
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.REVALIDATING
    assert current.prepared_audio_ref == "audio-g2"
    assert "audio-g1" not in owner.refs
    assert "audio-g2" in owner.refs


@pytest.mark.asyncio
async def test_post_check_generation_race_cannot_mutate_new_revalidation_generation() -> None:
    runtime = _PostCheckGenerationRaceRuntime()
    await runtime.register(_prepared("candidate", LLMPriority.FOREGROUND))
    coordinator = _coordinator(runtime, PreparedSpeechQueue(2))
    assert await coordinator.enqueue_current("candidate", 1, foreground=True)
    assert (await coordinator.pop_for_revalidation()) is not None
    runtime.inject_race = True
    with pytest.raises(ValueError, match="generation"):
        await coordinator.complete_revalidation("candidate", passed=True)
    current = await runtime.candidate("candidate")
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.REVALIDATING
    assert current.utterance_id == "utterance-g2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    [CandidateLifecycle.CANCELLED, CandidateLifecycle.STALE, CandidateLifecycle.SUPERSEDED],
)
async def test_pop_uses_live_terminal_state_not_queued_snapshot(
    terminal: CandidateLifecycle,
) -> None:
    runtime = SpeechRuntime()
    await runtime.register(_prepared("candidate", LLMPriority.FOREGROUND))
    coordinator = _coordinator(runtime, PreparedSpeechQueue(2))
    assert await coordinator.enqueue_current("candidate", 1, foreground=True)
    await runtime.cancel("candidate", terminal)
    assert await coordinator.pop_for_revalidation() is None


@pytest.mark.asyncio
async def test_bounded_fairness_serves_eligible_background_after_foreground_burst() -> None:
    runtime = SpeechRuntime()
    for candidate_id, priority in (
        ("background", LLMPriority.BACKGROUND),
        ("foreground-1", LLMPriority.FOREGROUND),
        ("foreground-2", LLMPriority.FOREGROUND),
    ):
        await runtime.register(_prepared(candidate_id, priority))
    coordinator = _coordinator(runtime, PreparedSpeechQueue(3, 1))
    assert await coordinator.enqueue_current("background", 1, foreground=False)
    assert await coordinator.enqueue_current("foreground-1", 1, foreground=True)
    assert await coordinator.enqueue_current("foreground-2", 1, foreground=True)
    assert (await coordinator.pop_for_revalidation()).candidate_id == "foreground-1"  # type: ignore[union-attr]
    assert (await coordinator.pop_for_revalidation()).candidate_id == "background"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_old_generation_entry_is_dropped_before_revalidation() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_prepared("candidate", LLMPriority.FOREGROUND))
    coordinator = _coordinator(runtime, PreparedSpeechQueue(1))
    assert await coordinator.enqueue_current("candidate", 1, foreground=True)
    await runtime.supersede_generation("candidate")
    assert await coordinator.pop_for_revalidation() is None
