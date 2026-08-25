from __future__ import annotations

import asyncio

import pytest

from app.domain.llm import LLMPriority
from app.domain.speech_runtime.admission import (
    SpeechPreparationAdmission,
    SpeechPreparationAdmissionPolicy,
)
from app.domain.speech_runtime.contracts import TTSPreparationMode
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.tasks import CandidateTaskRegistry


@pytest.mark.asyncio
async def test_character_fan_out_does_not_wait_for_blocked_verifier() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    performance_done = asyncio.Event()

    async def verifier() -> object:
        entered.set()
        await release.wait()
        return object()

    async def performance() -> object:
        performance_done.set()
        return object()

    tasks = CandidateTaskRegistry()
    orchestrator = SpeechPreparationOrchestrator(
        tasks, SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(2, 2, 4))
    )
    verifier_task, performance_task = orchestrator.fan_out_after_character(
        "candidate", 1, verifier, performance
    )
    await entered.wait()
    await performance_done.wait()
    assert not verifier_task.done()
    assert performance_task.done()
    release.set()
    await verifier_task


@pytest.mark.asyncio
async def test_speculative_tts_starts_without_verifier_acceptance() -> None:
    done = asyncio.Event()

    async def tts() -> object:
        done.set()
        return object()

    tasks = CandidateTaskRegistry()
    task = SpeechPreparationOrchestrator(
        tasks, SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(2, 2, 4))
    ).start_tts_if_permitted(
        "candidate", 1, TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE, False, tts
    )
    assert task is not None
    await done.wait()
    await task


@pytest.mark.asyncio
async def test_authoritative_preparation_entry_bounds_background_burst_and_reserves_foreground(
) -> None:
    admission = SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(1, 1, 2))
    tasks = CandidateTaskRegistry()
    orchestrator = SpeechPreparationOrchestrator(tasks, admission)
    background_started = asyncio.Event()
    foreground_started = asyncio.Event()
    release = asyncio.Event()

    async def background() -> object:
        background_started.set()
        await release.wait()
        return object()

    async def foreground() -> object:
        foreground_started.set()
        await release.wait()
        return object()

    background_tasks = [
        orchestrator.start_preparation(f"background-{index}", 1, LLMPriority.BACKGROUND, background)
        for index in range(100)
    ]
    await background_started.wait()
    await asyncio.sleep(0)
    assert admission.active_count == 1
    assert sum(task.done() for task in background_tasks) >= 99

    foreground_task = orchestrator.start_preparation(
        "foreground", 1, LLMPriority.FOREGROUND, foreground
    )
    await foreground_started.wait()
    assert admission.active_count == 2
    release.set()
    await asyncio.gather(*background_tasks, foreground_task, return_exceptions=True)
    assert admission.active_count == 0


@pytest.mark.asyncio
async def test_registered_preparation_is_shutdown_visible_and_releases_admission_lease() -> None:
    admission = SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(1, 1, 2))
    tasks = CandidateTaskRegistry()
    orchestrator = SpeechPreparationOrchestrator(tasks, admission)
    entered = asyncio.Event()

    async def blocked() -> object:
        entered.set()
        await asyncio.Event().wait()
        return object()

    task = orchestrator.start_preparation("candidate", 1, LLMPriority.BACKGROUND, blocked)
    await entered.wait()
    assert admission.active_count == 1
    await tasks.shutdown()
    assert task.cancelled()
    assert admission.active_count == 0
