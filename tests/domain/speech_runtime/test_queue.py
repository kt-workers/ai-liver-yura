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


@pytest.mark.asyncio
async def test_only_current_generation_can_enqueue_and_duplicate_is_rejected() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_prepared("candidate", LLMPriority.FOREGROUND))
    coordinator = PreparedSpeechQueueCoordinator(runtime, PreparedSpeechQueue(2))
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
    coordinator = PreparedSpeechQueueCoordinator(runtime, PreparedSpeechQueue(1))
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
    queue = PreparedSpeechQueueCoordinator(runtime, PreparedSpeechQueue(2))
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
    closed = await SpeechRuntimeShutdown(runtime, tasks, queue).close()
    assert set(closed) == {"candidate-a", "candidate-b"}
    assert task.cancelled()
    assert tasks.pending_task_count == 0
    assert len(queue) == 0
    assert (await runtime.candidate("candidate-a")).lifecycle is CandidateLifecycle.CANCELLED


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
    coordinator = PreparedSpeechQueueCoordinator(runtime, PreparedSpeechQueue(2))
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
    coordinator = PreparedSpeechQueueCoordinator(runtime, PreparedSpeechQueue(3, 1))
    assert await coordinator.enqueue_current("background", 1, foreground=False)
    assert await coordinator.enqueue_current("foreground-1", 1, foreground=True)
    assert await coordinator.enqueue_current("foreground-2", 1, foreground=True)
    assert (await coordinator.pop_for_revalidation()).candidate_id == "foreground-1"  # type: ignore[union-attr]
    assert (await coordinator.pop_for_revalidation()).candidate_id == "background"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_old_generation_entry_is_dropped_before_revalidation() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_prepared("candidate", LLMPriority.FOREGROUND))
    coordinator = PreparedSpeechQueueCoordinator(runtime, PreparedSpeechQueue(1))
    assert await coordinator.enqueue_current("candidate", 1, foreground=True)
    await runtime.supersede_generation("candidate")
    assert await coordinator.pop_for_revalidation() is None
