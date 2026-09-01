from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.llm import LLMInterruptibility
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
from app.domain.speech_runtime.policy import (
    SpeechCandidatePriority,
    SpeechQueueOverflowPolicy,
    SpeechRuntimeOperationalPolicy,
)
from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueCoordinator
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.shutdown import SpeechRuntimeShutdown
from app.domain.speech_runtime.tasks import CandidateTaskKey, CandidateTaskRegistry
from tests.domain.speech_runtime.policy_fixtures import runtime_policy


def _prepared(
    candidate_id: str,
    priority: SpeechCandidatePriority,
    policy: SpeechRuntimeOperationalPolicy | None = None,
    *,
    prepared_at: datetime | None = None,
) -> PreparedSpeechCandidate:
    bound_policy = runtime_policy() if policy is None else policy
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
        runtime_policy_id=bound_policy.policy_id,
        runtime_policy_revision=bound_policy.policy_revision,
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
        prepared_at=prepared_at or now,
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

    def __init__(self, policy: SpeechRuntimeOperationalPolicy) -> None:
        super().__init__(policy)
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
            await self.supersede_generation(candidate_id, self.generation(candidate_id))
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
            await self.begin_revalidation(candidate_id, 2)
        return await super().complete_revalidation(
            candidate_id, expected_generation, passed, failure
        )


class _QueuePopGenerationRaceRuntime(SpeechRuntime):
    def __init__(self, policy: SpeechRuntimeOperationalPolicy) -> None:
        super().__init__(policy)
        self.inject_race = False

    async def begin_revalidation(
        self, candidate_id: str, expected_generation: int
    ) -> PreparedSpeechCandidate | None:
        if self.inject_race:
            self.inject_race = False
            await self.supersede_generation(candidate_id, self.generation(candidate_id))
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
        return await super().begin_revalidation(candidate_id, expected_generation)


def _coordinator(
    runtime: SpeechRuntime,
    policy: SpeechRuntimeOperationalPolicy,
    owner: _DiscardOwner | None = None,
) -> PreparedSpeechQueueCoordinator:
    return PreparedSpeechQueueCoordinator(
        runtime,
        PreparedSpeechQueue(policy),
        PreparedAudioDiscarder(runtime, owner or _DiscardOwner()),
    )


@pytest.mark.asyncio
async def test_only_current_generation_can_enqueue_and_duplicate_is_rejected() -> None:
    policy = runtime_policy()
    runtime = SpeechRuntime(policy)
    await runtime.register(_prepared("candidate", SpeechCandidatePriority.FOREGROUND, policy))
    coordinator = _coordinator(runtime, policy)
    await runtime.supersede_generation("candidate", runtime.generation("candidate"))
    stale = await coordinator.enqueue_current("candidate", 1)
    assert not stale.admitted
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
    admitted = await coordinator.enqueue_current("candidate", 2)
    assert admitted.admitted_candidate_id == "candidate"
    duplicate = await coordinator.enqueue_current("candidate", 2)
    assert duplicate.rejected_candidate_id == "candidate"


@pytest.mark.asyncio
async def test_eviction_closes_displaced_lower_priority_candidate() -> None:
    policy = runtime_policy(
        queue_capacity=1,
        overflow_policy=SpeechQueueOverflowPolicy.EVICT_LOWEST_PRIORITY_OLDEST,
    )
    runtime = SpeechRuntime(policy)
    await runtime.register(_prepared("background", SpeechCandidatePriority.BACKGROUND, policy))
    await runtime.register(_prepared("foreground", SpeechCandidatePriority.FOREGROUND, policy))
    coordinator = _coordinator(runtime, policy)
    assert (await coordinator.enqueue_current("background", 1)).admitted
    result = await coordinator.enqueue_current("foreground", 1)
    assert result.admitted_candidate_id == "foreground"
    assert result.evicted_candidate_id == "background"
    assert (await runtime.candidate("background")).lifecycle is CandidateLifecycle.SUPERSEDED
    next_candidate = await coordinator.pop_for_revalidation()
    assert next_candidate is not None and next_candidate.candidate_id == "foreground"
    ready = await coordinator.complete_revalidation("foreground", passed=True)
    assert ready.lifecycle is CandidateLifecycle.READY_TO_PRESENT


@pytest.mark.asyncio
async def test_reject_new_records_rejected_candidate_without_silent_drop() -> None:
    policy = runtime_policy(queue_capacity=1, overflow_policy=SpeechQueueOverflowPolicy.REJECT_NEW)
    runtime = SpeechRuntime(policy)
    await runtime.register(_prepared("first", SpeechCandidatePriority.NORMAL, policy))
    await runtime.register(_prepared("second", SpeechCandidatePriority.FOREGROUND, policy))
    coordinator = _coordinator(runtime, policy)
    assert (await coordinator.enqueue_current("first", 1)).admitted
    result = await coordinator.enqueue_current("second", 1)
    assert result.rejected_candidate_id == "second"
    assert (await runtime.candidate("second")).lifecycle is CandidateLifecycle.SUPERSEDED


@pytest.mark.asyncio
async def test_canonical_queue_order_is_priority_then_prepared_at_then_candidate_id() -> None:
    policy = runtime_policy(queue_capacity=5)
    runtime = SpeechRuntime(policy)
    base = datetime.now(timezone.utc)
    candidates = (
        _prepared(
            "normal",
            SpeechCandidatePriority.NORMAL,
            policy,
            prepared_at=base - timedelta(seconds=10),
        ),
        _prepared("foreground-b", SpeechCandidatePriority.FOREGROUND, policy, prepared_at=base),
        _prepared("foreground-a", SpeechCandidatePriority.FOREGROUND, policy, prepared_at=base),
        _prepared(
            "direct",
            SpeechCandidatePriority.DIRECT_USER,
            policy,
            prepared_at=base + timedelta(seconds=10),
        ),
    )
    for candidate in candidates:
        await runtime.register(candidate)
    coordinator = _coordinator(runtime, policy)
    for candidate in candidates:
        assert (await coordinator.enqueue_current(candidate.candidate_id, 1)).admitted
    popped: list[str] = []
    while (candidate := await coordinator.pop_for_revalidation()) is not None:
        popped.append(candidate.candidate_id)
    assert popped == ["direct", "foreground-a", "foreground-b", "normal"]


@pytest.mark.asyncio
async def test_shutdown_cancels_candidate_local_tasks_and_drains_queue() -> None:
    policy = runtime_policy(queue_capacity=2)
    runtime = SpeechRuntime(policy)
    await runtime.register(_prepared("candidate-a", SpeechCandidatePriority.FOREGROUND, policy))
    await runtime.register(_prepared("candidate-b", SpeechCandidatePriority.BACKGROUND, policy))
    queue = _coordinator(runtime, policy)
    await queue.enqueue_current("candidate-a", 1)
    await queue.enqueue_current("candidate-b", 1)
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
    policy = runtime_policy(queue_capacity=1)
    runtime = SpeechRuntime(policy)
    candidate = replace(
        _prepared("candidate", SpeechCandidatePriority.FOREGROUND, policy),
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
    coordinator = _coordinator(runtime, policy, owner)
    closed = await SpeechRuntimeShutdown(
        runtime, CandidateTaskRegistry(), coordinator, PreparedAudioDiscarder(runtime, owner)
    ).close()
    assert closed == ("candidate",)
    assert not owner.refs
    assert owner.requests[0].audio_ref == "audio-candidate"
    assert (await runtime.candidate("candidate")).prepared_audio_ref is None


@pytest.mark.asyncio
async def test_queue_eviction_discards_displaced_audio_resource() -> None:
    policy = runtime_policy(
        queue_capacity=1,
        overflow_policy=SpeechQueueOverflowPolicy.EVICT_LOWEST_PRIORITY_OLDEST,
    )
    runtime = SpeechRuntime(policy)
    background = replace(
        _prepared("background", SpeechCandidatePriority.BACKGROUND, policy),
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
    await runtime.register(_prepared("foreground", SpeechCandidatePriority.FOREGROUND, policy))
    owner = _DiscardOwner("audio-background")
    coordinator = _coordinator(runtime, policy, owner)
    assert (await coordinator.enqueue_current("background", 1)).admitted
    result = await coordinator.enqueue_current("foreground", 1)
    assert result.evicted_candidate_id == "background"
    assert owner.requests[0].audio_ref == "audio-background"
    displaced = await runtime.candidate("background")
    assert displaced.lifecycle is CandidateLifecycle.SUPERSEDED
    assert displaced.prepared_audio_ref is None


@pytest.mark.asyncio
async def test_old_revalidation_failure_cannot_terminalize_new_generation_after_slow_discard() -> None:
    policy = runtime_policy(queue_capacity=2)
    runtime = SpeechRuntime(policy)
    candidate = replace(
        _prepared("candidate", SpeechCandidatePriority.FOREGROUND, policy),
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
    coordinator = _coordinator(runtime, policy, owner)
    assert (await coordinator.enqueue_current("candidate", 1)).admitted
    assert (await coordinator.pop_for_revalidation()) is not None
    stale_g1 = asyncio.create_task(
        coordinator.complete_revalidation(
            "candidate", passed=False, failure=CandidateLifecycle.STALE
        )
    )
    await owner.entered.wait()
    await runtime.supersede_generation("candidate", runtime.generation("candidate"))
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
    assert (await coordinator.enqueue_current("candidate", 2)).admitted
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
    policy = runtime_policy(queue_capacity=2)
    runtime = _PostCheckGenerationRaceRuntime(policy)
    await runtime.register(_prepared("candidate", SpeechCandidatePriority.FOREGROUND, policy))
    coordinator = _coordinator(runtime, policy)
    assert (await coordinator.enqueue_current("candidate", 1)).admitted
    assert (await coordinator.pop_for_revalidation()) is not None
    runtime.inject_race = True
    with pytest.raises(ValueError, match="generation"):
        await coordinator.complete_revalidation("candidate", passed=True)
    current = await runtime.candidate("candidate")
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.REVALIDATING
    assert current.utterance_id == "utterance-g2"


@pytest.mark.asyncio
async def test_stale_queue_pop_cannot_revalidate_generation_two() -> None:
    policy = runtime_policy(queue_capacity=2)
    runtime = _QueuePopGenerationRaceRuntime(policy)
    await runtime.register(_prepared("candidate", SpeechCandidatePriority.FOREGROUND, policy))
    coordinator = _coordinator(runtime, policy)
    assert (await coordinator.enqueue_current("candidate", 1)).admitted
    runtime.inject_race = True
    assert await coordinator.pop_for_revalidation() is None
    current = await runtime.candidate("candidate")
    assert runtime.generation("candidate") == 2
    assert current.lifecycle is CandidateLifecycle.QUEUED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal",
    [CandidateLifecycle.CANCELLED, CandidateLifecycle.STALE, CandidateLifecycle.SUPERSEDED],
)
async def test_pop_uses_live_terminal_state_not_queued_snapshot(
    terminal: CandidateLifecycle,
) -> None:
    policy = runtime_policy(queue_capacity=2)
    runtime = SpeechRuntime(policy)
    await runtime.register(_prepared("candidate", SpeechCandidatePriority.FOREGROUND, policy))
    coordinator = _coordinator(runtime, policy)
    assert (await coordinator.enqueue_current("candidate", 1)).admitted
    await runtime.cancel(
        "candidate", terminal, expected_generation=runtime.generation("candidate")
    )
    assert await coordinator.pop_for_revalidation() is None
