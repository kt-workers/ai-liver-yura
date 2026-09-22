"""非同期作業の開始前後の取消で、後続候補へ準備枠を返すことを確認する。"""

import asyncio

import pytest

from app.domain.speech_runtime.admission import SpeechPreparationAdmission
from app.domain.speech_runtime.contracts import TTSPreparationMode
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.domain.speech_runtime.tasks import CandidateTaskRegistry
from tests.domain.speech_runtime.policy_fixtures import runtime_policy


async def ready() -> object:
    return object()


@pytest.mark.asyncio
async def test_preparation_cancelled_before_start_releases_global_and_background_slots() -> None:
    tasks = CandidateTaskRegistry()
    admission = SpeechPreparationAdmission(
        runtime_policy(max_in_flight=1, max_background_in_flight=1)
    )
    owner = SpeechPreparationOrchestrator(tasks, admission)
    first = owner.start_preparation("first", 1, SpeechCandidatePriority.BACKGROUND, ready)
    assert first is not None
    await tasks.cancel_candidate("first")
    assert first.cancelled()
    assert admission.active_count == admission.background_active_count == 0
    second = owner.start_preparation("second", 1, SpeechCandidatePriority.BACKGROUND, ready)
    assert second is not None
    await second
    await tasks.shutdown()
    assert admission.active_count == admission.background_active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_cancelled_speculation_does_not_starve_next_candidate(started: bool) -> None:
    tasks = CandidateTaskRegistry()
    admission = SpeechPreparationAdmission(runtime_policy(speculative_tts_limit=1))
    owner = SpeechPreparationOrchestrator(tasks, admission)
    for name in ("first", "second"):
        task = owner.start_preparation(name, 1, SpeechCandidatePriority.FOREGROUND, ready)
        assert task is not None
        await task
    entered = asyncio.Event()

    async def blocked() -> object:
        entered.set()
        await asyncio.Event().wait()
        return object()

    first = owner.start_tts_if_permitted(
        "first", 1, TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE, False, blocked
    )
    assert first is not None
    if started:
        await entered.wait()
    await tasks.cancel_candidate("first")
    assert first.cancelled() and entered.is_set() is started
    assert owner.active_speculative_tts_count == 0
    second = owner.start_tts_if_permitted(
        "second", 1, TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE, False, ready
    )
    assert second is not None
    await second
    assert owner.active_speculative_tts_count == 0
    await tasks.shutdown()
    assert admission.active_count == 0


@pytest.mark.asyncio
async def test_duplicate_synthesis_registration_does_not_consume_another_slot() -> None:
    tasks = CandidateTaskRegistry()
    admission = SpeechPreparationAdmission(runtime_policy(speculative_tts_limit=2))
    owner = SpeechPreparationOrchestrator(tasks, admission)
    character = owner.start_preparation("candidate", 1, SpeechCandidatePriority.FOREGROUND, ready)
    assert character is not None
    await character
    first = owner.start_tts_if_permitted(
        "candidate", 1, TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE, False, ready
    )
    assert first is not None
    with pytest.raises(ValueError, match="重複"):
        owner.start_tts_if_permitted(
            "candidate", 1, TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE, False, ready
        )
    assert owner.active_speculative_tts_count == 1
    await first
    await tasks.shutdown()
    assert owner.active_speculative_tts_count == admission.active_count == 0
