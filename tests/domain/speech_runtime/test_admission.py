from __future__ import annotations

import asyncio

import pytest

from app.domain.speech_runtime.admission import (
    AdmittedPreparationExecutor,
    SpeechPreparationAdmission,
)
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from tests.domain.speech_runtime.policy_fixtures import runtime_policy


def test_background_burst_never_exceeds_closed_admission_bound() -> None:
    policy = runtime_policy(max_in_flight=4, max_background_in_flight=3)
    admission = SpeechPreparationAdmission(policy)
    started = sum(
        admission.try_acquire(SpeechCandidatePriority.BACKGROUND) for _ in range(100)
    )
    assert started == 3
    assert admission.try_acquire(SpeechCandidatePriority.DIRECT_USER)
    assert not admission.try_acquire(SpeechCandidatePriority.FOREGROUND)


def test_direct_user_is_not_starved_by_background_admission() -> None:
    policy = runtime_policy(max_in_flight=4, max_background_in_flight=3)
    admission = SpeechPreparationAdmission(policy)
    for _ in range(3):
        assert admission.try_acquire(SpeechCandidatePriority.BACKGROUND)
    assert admission.try_acquire(SpeechCandidatePriority.DIRECT_USER)


@pytest.mark.asyncio
async def test_in_flight_background_burst_is_bounded_and_cancellation_releases_lease() -> None:
    policy = runtime_policy(max_in_flight=4, max_background_in_flight=2)
    admission = SpeechPreparationAdmission(policy)
    executor = AdmittedPreparationExecutor(admission)
    entered, release = asyncio.Event(), asyncio.Event()

    async def work() -> int:
        entered.set()
        await release.wait()
        return 1

    tasks = [
        asyncio.create_task(executor.run(SpeechCandidatePriority.BACKGROUND, work))
        for _ in range(100)
    ]
    await entered.wait()
    await asyncio.sleep(0)
    assert admission.active_count <= 2
    assert admission.background_active_count <= 2
    assert sum(task.done() for task in tasks) >= 98
    release.set()
    await asyncio.gather(*tasks)
    assert admission.active_count == 0
    assert admission.background_active_count == 0
