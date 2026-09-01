from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.domain.llm import LLMPriority
from app.domain.speech_runtime.admission import (
    SpeechPreparationAdmission,
    SpeechPreparationAdmissionPolicy,
)
from app.domain.speech_runtime.contracts import TTSPreparationMode
from app.domain.speech_runtime.discard import PreparedAudioDiscarder
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.policy import (
    V2_SPEECH_RUNTIME_OPERATIONAL_POLICY,
    SpeechRuntimeOperationalPolicy,
)
from app.domain.speech_runtime.queue import PreparedSpeechQueue
from app.domain.speech_runtime.repair import SemanticRepairEvidence, SpeechSemanticRepairExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry
from tests.domain.speech_runtime.test_queue import _prepared
from tests.domain.speech_runtime.test_repair import _FakeOwner, _candidate


class MutableMonotonicClock:
    def __init__(self, value: int = 0) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


@pytest.mark.parametrize(
    "field_name",
    [
        "queue_max_candidates",
        "queue_max_consecutive_foreground",
        "prepared_candidate_ttl_ms",
        "revalidation_max_age_ms",
        "repair_max_generation_attempts",
        "repair_evidence_max_refs",
        "speculative_tts_parallelism_per_candidate",
    ],
)
def test_policy_rejects_bool_as_int(field_name: str) -> None:
    with pytest.raises(ValueError):
        replace(V2_SPEECH_RUNTIME_OPERATIONAL_POLICY, **{field_name: True})


def test_default_policy_matches_d10_contract() -> None:
    policy = V2_SPEECH_RUNTIME_OPERATIONAL_POLICY
    assert policy.queue_max_candidates == 8
    assert policy.queue_max_consecutive_foreground == 3
    assert policy.prepared_candidate_ttl_ms == 15000
    assert policy.revalidation_max_age_ms == 3000
    assert policy.repair_max_generation_attempts == 1
    assert policy.repair_evidence_max_refs == 64
    assert policy.speculative_tts_parallelism_per_candidate == 1


def test_policy_rejects_invalid_cross_field_and_v1_fixed_values() -> None:
    with pytest.raises(ValueError):
        replace(
            V2_SPEECH_RUNTIME_OPERATIONAL_POLICY,
            prepared_candidate_ttl_ms=3000,
            revalidation_max_age_ms=3000,
        )
    with pytest.raises(ValueError):
        replace(V2_SPEECH_RUNTIME_OPERATIONAL_POLICY, repair_max_generation_attempts=2)
    with pytest.raises(ValueError):
        replace(
            V2_SPEECH_RUNTIME_OPERATIONAL_POLICY,
            speculative_tts_parallelism_per_candidate=2,
        )


@pytest.mark.asyncio
async def test_prepared_candidate_ttl_14999_15000_boundary_uses_monotonic_only() -> None:
    clock = MutableMonotonicClock(1000)
    runtime = SpeechRuntime(monotonic_ms=clock)
    candidate = _prepared("ttl", LLMPriority.FOREGROUND)
    await runtime.register(candidate)
    bound = await runtime.candidate("ttl")
    assert bound.runtime_policy_id == V2_SPEECH_RUNTIME_OPERATIONAL_POLICY.policy_id
    assert bound.prepared_ttl_ms == 15000

    clock.value = 15999
    assert await runtime.operational_failure("ttl") is None
    clock.value = 16000
    assert await runtime.operational_failure("ttl") == "prepared_candidate_expired"

    wall_clock_changed = replace(candidate, expires_at=candidate.created_at)
    legacy_runtime = SpeechRuntime(monotonic_ms=MutableMonotonicClock(0))
    await legacy_runtime.register(wall_clock_changed)
    assert await legacy_runtime.operational_failure("ttl") is None


@pytest.mark.asyncio
async def test_revalidation_age_3000_3001_boundary() -> None:
    clock = MutableMonotonicClock(0)
    runtime = SpeechRuntime(monotonic_ms=clock)
    await runtime.register(_prepared("revalidation", LLMPriority.FOREGROUND))
    assert await runtime.queue_for_generation("revalidation", 1) is not None
    clock.value = 100
    begun = await runtime.begin_revalidation("revalidation", 1)
    assert begun is not None
    assert begun.revalidation_started_mono_ms == 100

    clock.value = 3100
    assert await runtime.operational_failure("revalidation") is None
    clock.value = 3101
    assert await runtime.operational_failure("revalidation") == "revalidation_too_old"


@pytest.mark.asyncio
async def test_policy_revision_change_never_rebinds_old_candidate_limits() -> None:
    clock = MutableMonotonicClock(0)
    runtime = SpeechRuntime(monotonic_ms=clock)
    await runtime.register(_prepared("policy", LLMPriority.FOREGROUND))
    old = await runtime.candidate("policy")
    next_policy = replace(
        V2_SPEECH_RUNTIME_OPERATIONAL_POLICY,
        policy_revision=V2_SPEECH_RUNTIME_OPERATIONAL_POLICY.policy_revision + 1,
        prepared_candidate_ttl_ms=20000,
    )
    await runtime.update_operational_policy(next_policy)
    assert await runtime.operational_failure("policy") == "runtime_policy_stale"
    unchanged = await runtime.candidate("policy")
    assert unchanged.prepared_ttl_ms == old.prepared_ttl_ms == 15000
    assert unchanged.runtime_policy_revision != next_policy.policy_revision


def test_default_queue_capacity_8_9_and_foreground_fairness_3() -> None:
    queue = PreparedSpeechQueue()
    assert queue.policy == V2_SPEECH_RUNTIME_OPERATIONAL_POLICY
    for index in range(8):
        assert queue.enqueue(f"candidate-{index}", 1, foreground=False)
    assert not queue.enqueue("candidate-over", 1, foreground=False)

    fairness = PreparedSpeechQueue()
    for index in range(4):
        assert fairness.enqueue(f"fg-{index}", 1, foreground=True)
    assert fairness.enqueue("bg", 1, foreground=False)
    popped = [fairness.pop() for _ in range(4)]
    assert [item.candidate_id if item is not None else None for item in popped] == [
        "fg-0",
        "fg-1",
        "fg-2",
        "bg",
    ]


@pytest.mark.asyncio
async def test_repair_evidence_64_65_boundary_does_not_first_n_accept() -> None:
    runtime = SpeechRuntime()
    tasks = CandidateTaskRegistry()
    await runtime.register(_candidate("repair-64"))
    executor = SpeechSemanticRepairExecutor(
        runtime,
        tasks,
        PreparedAudioDiscarder(runtime, _FakeOwner()),
    )
    received: list[object] = []

    async def repair(attempt: object) -> None:
        received.append(attempt)

    refs_64 = tuple(f"evidence-{index}" for index in range(64))
    result = await executor.handle_verifier_result(
        candidate_id="repair-64",
        generation=1,
        semantic_accepted=False,
        semantic_acceptance_id=None,
        verifier_execution_failed=False,
        speech_plan_stale=False,
        evidence=SemanticRepairEvidence(("mismatch",), refs_64),
        repair_character=repair,
    )
    assert result is not None
    assert len(received) == 1

    runtime_over = SpeechRuntime()
    tasks_over = CandidateTaskRegistry()
    await runtime_over.register(_candidate("repair-65"))
    executor_over = SpeechSemanticRepairExecutor(
        runtime_over,
        tasks_over,
        PreparedAudioDiscarder(runtime_over, _FakeOwner()),
    )
    refs_65 = tuple(f"evidence-{index}" for index in range(65))
    with pytest.raises(ValueError, match="evidence refs"):
        await executor_over.handle_verifier_result(
            candidate_id="repair-65",
            generation=1,
            semantic_accepted=False,
            semantic_acceptance_id=None,
            verifier_execution_failed=False,
            speech_plan_stale=False,
            evidence=SemanticRepairEvidence(("mismatch",), refs_65),
            repair_character=repair,
        )
    assert runtime_over.generation("repair-65") == 1


@pytest.mark.asyncio
async def test_speculative_tts_parallelism_1_2_boundary() -> None:
    tasks = CandidateTaskRegistry()
    admission = SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(1, 1, 2))
    orchestrator = SpeechPreparationOrchestrator(tasks, admission)

    async def character() -> object:
        return object()

    character_task = orchestrator.start_preparation(
        "candidate",
        1,
        LLMPriority.FOREGROUND,
        character,
    )
    assert character_task is not None
    await character_task

    release = asyncio.Event()

    async def tts() -> object:
        await release.wait()
        return object()

    first = orchestrator.start_tts_if_permitted(
        "candidate",
        1,
        TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
        False,
        tts,
    )
    assert first is not None
    second = orchestrator.start_tts_if_permitted(
        "candidate",
        1,
        TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
        False,
        tts,
    )
    assert second is None
    release.set()
    await first
    orchestrator.complete_preparation("candidate", 1)
    await asyncio.sleep(0)
