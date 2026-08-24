from __future__ import annotations

import asyncio

import pytest

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
    orchestrator = SpeechPreparationOrchestrator(tasks)
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
    task = SpeechPreparationOrchestrator(tasks).start_tts_if_permitted(
        "candidate", 1, TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE, False, tts
    )
    assert task is not None
    await done.wait()
    await task
