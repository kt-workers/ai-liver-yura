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
    async def character() -> object:
        return object()

    character_task = orchestrator.start_preparation(
        "candidate", 1, LLMPriority.FOREGROUND, character
    )
    assert character_task is not None
    await character_task
    verifier_task, performance_task = orchestrator.fan_out_after_character(
        "candidate", 1, verifier, performance
    )
    await entered.wait()
    await performance_done.wait()
    assert not verifier_task.done()
    assert performance_task.done()
    release.set()
    await verifier_task
    orchestrator.complete_preparation("candidate", 1)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_speculative_tts_starts_without_verifier_acceptance() -> None:
    done = asyncio.Event()

    async def tts() -> object:
        done.set()
        return object()

    tasks = CandidateTaskRegistry()
    orchestrator = SpeechPreparationOrchestrator(
        tasks, SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(2, 2, 4))
    )
    async def character() -> object:
        return object()

    character_task = orchestrator.start_preparation(
        "candidate", 1, LLMPriority.FOREGROUND, character
    )
    assert character_task is not None
    await character_task
    task = orchestrator.start_tts_if_permitted(
        "candidate", 1, TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE, False, tts
    )
    assert task is not None
    await done.wait()
    await task
    orchestrator.complete_preparation("candidate", 1)
    await asyncio.sleep(0)


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
    assert sum(task is None for task in background_tasks) >= 99

    foreground_task = orchestrator.start_preparation(
        "foreground", 1, LLMPriority.FOREGROUND, foreground
    )
    await foreground_started.wait()
    assert admission.active_count == 2
    release.set()
    active_tasks = [task for task in (*background_tasks, foreground_task) if task is not None]
    await asyncio.gather(*active_tasks)
    orchestrator.complete_preparation("background-0", 1)
    orchestrator.complete_preparation("foreground", 1)
    await asyncio.sleep(0)
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
    assert task is not None
    await entered.wait()
    assert admission.active_count == 1
    await tasks.shutdown()
    assert task.cancelled()
    assert admission.active_count == 0


@pytest.mark.asyncio
async def test_background_burst_cannot_fan_out_after_fast_character_completion() -> None:
    admission = SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(1, 1, 2))
    tasks = CandidateTaskRegistry()
    orchestrator = SpeechPreparationOrchestrator(tasks, admission)
    release = asyncio.Event()

    async def character() -> object:
        return object()

    async def blocked() -> object:
        await release.wait()
        return object()

    character_tasks = [
        orchestrator.start_preparation(f"background-{index}", 1, LLMPriority.BACKGROUND, character)
        for index in range(100)
    ]
    admitted = [task for task in character_tasks if task is not None]
    assert len(admitted) == 1
    await admitted[0]
    verifier, performance = orchestrator.fan_out_after_character(
        "background-0", 1, blocked, blocked
    )
    assert tasks.pending_task_count == 3  # admission lease + verifier + performance
    for index in range(1, 100):
        with pytest.raises(ValueError, match="admitted"):
            orchestrator.fan_out_after_character(f"background-{index}", 1, blocked, blocked)
    release.set()
    await asyncio.gather(verifier, performance)
    orchestrator.complete_preparation("background-0", 1)
    await asyncio.sleep(0)
    assert admission.active_count == 0
