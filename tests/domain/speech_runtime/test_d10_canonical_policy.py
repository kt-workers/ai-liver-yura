from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.domain.speech_runtime.admission import SpeechPreparationAdmission
from app.domain.speech_runtime.contracts import TTSPreparationMode
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.policy import (
    SpeechCandidatePriority,
    SpeechExpiryRule,
    SpeechQueueOverflowPolicy,
)
from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueEntry
from app.domain.speech_runtime.repair import semantic_repair_disposition
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_runtime.test_queue import _prepared
from tests.domain.speech_runtime.test_skip_proof import _request


class MutableAbsoluteClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_policy_strict_numeric_fields_reject_bool_and_zero_is_explicitly_supported() -> None:
    policy = runtime_policy()
    with pytest.raises(ValueError):
        replace(policy, prepared_queue_capacity=cast(int, True))
    with pytest.raises(ValueError):
        replace(policy, max_in_flight_preparations=cast(int, True))
    with pytest.raises(ValueError):
        replace(policy, max_background_in_flight_preparations=cast(int, True))
    with pytest.raises(ValueError):
        replace(policy, max_regeneration_attempts=cast(int, True))
    with pytest.raises(ValueError):
        replace(policy, speculative_tts_limit=cast(int, True))
    zero_policy = replace(
        policy,
        max_background_in_flight_preparations=0,
        max_regeneration_attempts=0,
        speculative_tts_limit=0,
    )
    assert zero_policy.max_background_in_flight_preparations == 0
    assert zero_policy.max_regeneration_attempts == 0
    assert zero_policy.speculative_tts_limit == 0


def test_expiry_rule_rejects_bool_nonfinite_nonpositive_and_incomplete_coverage() -> None:
    with pytest.raises(ValueError):
        SpeechExpiryRule(SpeechCandidatePriority.FOREGROUND, cast(float, True))
    for invalid in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
        with pytest.raises(ValueError):
            SpeechExpiryRule(SpeechCandidatePriority.FOREGROUND, invalid)

    policy = runtime_policy()
    with pytest.raises(ValueError, match="exactly once"):
        replace(policy, expiry_rules=policy.expiry_rules[:-1])
    with pytest.raises(ValueError, match="一意"):
        replace(policy, expiry_rules=(*policy.expiry_rules, policy.expiry_rules[0]))


def test_production_runtime_queue_and_admission_have_no_hidden_policy_default() -> None:
    with pytest.raises(TypeError):
        cast(Any, SpeechRuntime)()
    with pytest.raises(TypeError):
        cast(Any, PreparedSpeechQueue)()
    with pytest.raises(TypeError):
        cast(Any, SpeechPreparationAdmission)()


@pytest.mark.asyncio
async def test_expiry_uses_absolute_utc_elapsed_time_and_equality_is_still_valid() -> None:
    policy = runtime_policy(foreground_age_seconds=10.0)
    created_at = datetime(
        2026,
        9,
        1,
        12,
        0,
        0,
        tzinfo=timezone(timedelta(hours=9)),
    )
    utc_created = created_at.astimezone(timezone.utc)
    clock = MutableAbsoluteClock(utc_created + timedelta(seconds=9, milliseconds=999))
    runtime = SpeechRuntime(policy, clock)
    candidate = replace(
        _prepared("expiry", SpeechCandidatePriority.FOREGROUND, policy),
        created_at=created_at,
        updated_at=created_at,
        prepared_at=created_at,
    )
    await runtime.register(candidate)

    assert await runtime.operational_failure("expiry") is None
    clock.value = utc_created + timedelta(seconds=10)
    assert await runtime.operational_failure("expiry") is None
    clock.value = utc_created + timedelta(seconds=10, milliseconds=1)
    assert await runtime.operational_failure("expiry") == "candidate_expired"


@pytest.mark.asyncio
async def test_policy_revision_change_marks_old_candidate_stale_without_rebinding() -> None:
    policy = runtime_policy(revision=1)
    runtime = SpeechRuntime(policy)
    candidate = _prepared("policy", SpeechCandidatePriority.NORMAL, policy)
    await runtime.register(candidate)
    next_policy = replace(policy, policy_revision=2)
    await runtime.update_operational_policy(next_policy)

    assert await runtime.operational_failure("policy") == "runtime_policy_stale"
    current = await runtime.candidate("policy")
    assert current.runtime_policy_revision == 1
    assert current.runtime_policy_id == policy.policy_id


def test_repair_bound_supports_zero_one_and_multiple_regenerations() -> None:
    common = {
        "semantic_accepted": False,
        "verifier_execution_failed": False,
        "speech_plan_stale": False,
    }
    assert semantic_repair_disposition(
        **common, repair_count=0, maximum_attempts=0
    ).value == "rejected_final"
    assert semantic_repair_disposition(
        **common, repair_count=0, maximum_attempts=1
    ).value == "repair_once"
    assert semantic_repair_disposition(
        **common, repair_count=1, maximum_attempts=1
    ).value == "rejected_final"
    for repair_count in (0, 1, 2):
        assert semantic_repair_disposition(
            **common,
            repair_count=repair_count,
            maximum_attempts=3,
        ).value == "repair_once"
    assert semantic_repair_disposition(
        **common, repair_count=3, maximum_attempts=3
    ).value == "rejected_final"


def test_background_preparation_limit_zero_reserves_runtime_for_non_background_work() -> None:
    policy = runtime_policy(max_in_flight=1, max_background_in_flight=0)
    admission = SpeechPreparationAdmission(policy)
    assert not admission.try_acquire(SpeechCandidatePriority.BACKGROUND)
    assert admission.try_acquire(SpeechCandidatePriority.DIRECT_USER)
    admission.release(SpeechCandidatePriority.DIRECT_USER)
    assert admission.active_count == 0


def test_evict_policy_rejects_new_candidate_when_it_is_lower_priority() -> None:
    policy = runtime_policy(
        queue_capacity=1,
        overflow_policy=SpeechQueueOverflowPolicy.EVICT_LOWEST_PRIORITY_OLDEST,
    )
    queue = PreparedSpeechQueue(policy)
    now = datetime.now(timezone.utc)
    first = queue.enqueue(
        PreparedSpeechQueueEntry(
            "foreground",
            1,
            SpeechCandidatePriority.FOREGROUND,
            now,
        )
    )
    assert first.admitted_candidate_id == "foreground"
    rejected = queue.enqueue(
        PreparedSpeechQueueEntry(
            "background",
            1,
            SpeechCandidatePriority.BACKGROUND,
            now + timedelta(seconds=1),
        )
    )
    assert rejected.rejected_candidate_id == "background"
    assert rejected.evicted_candidate_id is None
    remaining = queue.pop()
    assert remaining is not None and remaining.candidate_id == "foreground"


@pytest.mark.asyncio
async def test_speculative_tts_limit_is_global_and_accepted_required_tts_is_excluded() -> None:
    policy = runtime_policy(
        max_in_flight=3,
        max_background_in_flight=1,
        speculative_tts_limit=1,
    )
    tasks = CandidateTaskRegistry()
    admission = SpeechPreparationAdmission(policy)
    orchestrator = SpeechPreparationOrchestrator(tasks, admission)

    async def character() -> object:
        return object()

    for candidate_id in ("candidate-a", "candidate-b"):
        task = orchestrator.start_preparation(
            candidate_id,
            1,
            SpeechCandidatePriority.FOREGROUND,
            character,
        )
        assert task is not None
        await task

    speculative_release = asyncio.Event()
    required_release = asyncio.Event()

    async def speculative_tts() -> object:
        await speculative_release.wait()
        return object()

    async def required_tts() -> object:
        await required_release.wait()
        return object()

    first = orchestrator.start_tts_if_permitted(
        "candidate-a",
        1,
        TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
        False,
        speculative_tts,
    )
    assert first is not None
    assert orchestrator.active_speculative_tts_count == 1
    second_speculative = orchestrator.start_tts_if_permitted(
        "candidate-b",
        1,
        TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
        False,
        speculative_tts,
    )
    assert second_speculative is None

    required = orchestrator.start_tts_if_permitted(
        "candidate-b",
        1,
        TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE,
        True,
        required_tts,
    )
    assert required is not None
    assert orchestrator.active_speculative_tts_count == 1

    speculative_release.set()
    required_release.set()
    await asyncio.gather(first, required)
    assert orchestrator.active_speculative_tts_count == 0
    orchestrator.complete_preparation("candidate-a", 1)
    orchestrator.complete_preparation("candidate-b", 1)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_speculative_limit_zero_blocks_speculation_but_not_accepted_required_tts() -> None:
    policy = runtime_policy(speculative_tts_limit=0)
    tasks = CandidateTaskRegistry()
    admission = SpeechPreparationAdmission(policy)
    orchestrator = SpeechPreparationOrchestrator(tasks, admission)

    async def work() -> object:
        return object()

    character = orchestrator.start_preparation(
        "candidate",
        1,
        SpeechCandidatePriority.FOREGROUND,
        work,
    )
    assert character is not None
    await character
    assert (
        orchestrator.start_tts_if_permitted(
            "candidate",
            1,
            TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
            False,
            work,
        )
        is None
    )
    required = orchestrator.start_tts_if_permitted(
        "candidate",
        1,
        TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE,
        True,
        work,
    )
    assert required is not None
    await required
    orchestrator.complete_preparation("candidate", 1)
    await asyncio.sleep(0)


def test_request_and_candidate_keep_runtime_policy_generation_provenance() -> None:
    request = _request()
    policy = runtime_policy()
    candidate = _prepared("candidate", SpeechCandidatePriority.NORMAL, policy)
    assert request.runtime_policy_id == policy.policy_id
    assert request.runtime_policy_revision == policy.policy_revision
    assert candidate.runtime_policy_id == policy.policy_id
    assert candidate.runtime_policy_revision == policy.policy_revision
