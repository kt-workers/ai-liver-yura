from __future__ import annotations

import asyncio

import pytest

from app.domain.llm import LLMPriority
from app.domain.speech_runtime.admission import (
    AdmittedPreparationExecutor,
    SpeechPreparationAdmission,
    SpeechPreparationAdmissionPolicy,
)


def test_background_burst_never_exceeds_closed_admission_bound() -> None:
    admission = SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(2, 3, 4))
    started = sum(admission.try_acquire(LLMPriority.BACKGROUND) for _ in range(100))
    assert started == 3
    assert admission.try_acquire(LLMPriority.FOREGROUND)
    assert not admission.try_acquire(LLMPriority.FOREGROUND)


def test_foreground_is_not_starved_by_background_admission() -> None:
    admission = SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(2, 3, 4))
    for _ in range(3):
        assert admission.try_acquire(LLMPriority.BACKGROUND)
    assert admission.try_acquire(LLMPriority.FOREGROUND)


@pytest.mark.asyncio
async def test_in_flight_background_burst_is_bounded_and_cancellation_releases_lease() -> None:
    admission = SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(2, 2, 4))
    executor = AdmittedPreparationExecutor(admission)
    entered, release = asyncio.Event(), asyncio.Event()

    async def work() -> int:
        entered.set()
        await release.wait()
        return 1

    tasks = [asyncio.create_task(executor.run(LLMPriority.BACKGROUND, work)) for _ in range(100)]
    await entered.wait()
    await asyncio.sleep(0)
    assert admission.active_count <= 2
    assert sum(task.done() for task in tasks) >= 98
    release.set()
    await asyncio.gather(*tasks)
    assert admission.active_count == 0
