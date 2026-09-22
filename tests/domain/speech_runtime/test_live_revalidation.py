"""現在状態の再照合と提示確定が同じ契約を用いることを確認する。"""

from dataclasses import replace

import pytest

from app.domain.speech_runtime.contracts import CandidateLifecycle, SpeechPresentationCommitState
from tests.domain.speech_runtime.policy_fixtures import TestSpeechRuntime
from tests.domain.speech_runtime.test_presentation import (
    _ready_candidate,
    _state,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        replace(_state(), source_context_revision=99),
        replace(_state(), semantic_acceptance_id="different"),
        replace(_state(), performance_plan_id="different"),
        replace(_state(), satisfied_preconditions=()),
        replace(_state(), character_compatible=False),
        replace(_state(), expiry_valid=False),
    ],
)
async def test_revalidation_rejects_same_mismatches_as_presentation(
    state: SpeechPresentationCommitState,
) -> None:
    runtime = TestSpeechRuntime()
    candidate = replace(_ready_candidate(), lifecycle=CandidateLifecycle.REVALIDATING)
    await runtime.register(candidate)
    with pytest.raises(ValueError):
        await runtime.revalidate_current(candidate.candidate_id, 1, state)
    assert (
        await runtime.candidate(candidate.candidate_id)
    ).lifecycle is CandidateLifecycle.REVALIDATING


@pytest.mark.asyncio
async def test_stale_generation_does_not_promote_and_commit_rechecks_after_valid_revalidation() -> (
    None
):
    runtime = TestSpeechRuntime()
    candidate = replace(_ready_candidate(), lifecycle=CandidateLifecycle.REVALIDATING)
    await runtime.register(candidate)
    assert await runtime.revalidate_current(candidate.candidate_id, 2, _state()) is None
    ready = await runtime.revalidate_current(candidate.candidate_id, 1, _state())
    assert ready is not None and ready.lifecycle is CandidateLifecycle.READY_TO_PRESENT
    with pytest.raises(ValueError):
        await runtime.commit(
            candidate.candidate_id, replace(_state(), source_context_revision=99), "p"
        )
    assert (
        await runtime.candidate(candidate.candidate_id)
    ).lifecycle is CandidateLifecycle.READY_TO_PRESENT
