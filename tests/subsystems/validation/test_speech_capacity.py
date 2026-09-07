"""共有する本番準備枠の上限、合成の分離と取消回収を確認する。"""

import asyncio
from dataclasses import replace

import pytest

from app.adapters.tts.provider import ProviderSynthesisInput, TTSProviderResponse
from app.domain.speech_runtime.contracts import TTSPreparationMode
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.subsystems.validation.contracts import Gate, LabMode, LabRunSpec, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.speech_capacity import (
    SpeechCapacityCase,
    SpeechCapacityInput,
    speech_capacity_target,
)
from tests.adapters.tts import test_provider as tts
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec
from tests.subsystems.validation.test_tts import case as synthesis_case


def case(*, accepted: bool = False, limit: int = 1) -> SpeechCapacityCase:
    source = synthesis_case()
    priorities = (
        SpeechCandidatePriority.BACKGROUND,
        SpeechCandidatePriority.BACKGROUND,
        SpeechCandidatePriority.FOREGROUND,
        SpeechCandidatePriority.FOREGROUND,
    )
    inputs = tuple(
        SpeechCapacityInput(
            replace(source, request=replace(source.request, candidate_id=f"candidate-{index}")),
            priority,
            TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
            accepted,
        )
        for index, priority in enumerate(priorities)
    )
    value = SpeechCapacityCase(
        FIXTURE,
        runtime_policy(
            max_in_flight=2,
            max_background_in_flight=1,
            speculative_tts_limit=limit,
        ),
        inputs,
    )
    return replace(value, fixture=replace(FIXTURE, typed_inputs=value.typed_inputs()))


def run_spec(*, repeat_count: int = 1) -> LabRunSpec:
    return replace(
        spec(), target_module="speech_capacity", mode=LabMode.ADJACENT, repeat_count=repeat_count
    )


def runner(item: SpeechCapacityCase, client: tts.FakeTTS) -> ValidationRunner:
    return ValidationRunner(
        (speech_capacity_target((item,), client, PROVENANCE, "1"),),
        replace(POLICY, max_tasks=32, max_intervals=64),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted,limit,expected", [(False, 1, 1), (False, 0, 0), (True, 0, 2)])
async def test_shared_admission_and_speculative_limits_use_product_owner(
    accepted: bool,
    limit: int,
    expected: int,
) -> None:
    item = case(accepted=accepted, limit=limit)
    client = tts.FakeTTS([tts._response() for _ in range(expected)])
    result = await runner(item, client).run(run_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    data = result.stage_results[0].typed_outputs
    assert [value_at(data, "candidates", i, "admitted") for i in range(4)] == [
        True,
        False,
        True,
        False,
    ]
    assert len(client.calls) == expected
    for name in (
        "admission_count_after_settlement",
        "background_count_after_settlement",
        "speculative_count_after_settlement",
        "pending_task_count",
    ):
        assert value_at(data, name) == 0
    if expected == 2:
        assert value_at(data, "candidates", 0, "result", "artifact", "candidate_id") != value_at(
            data, "candidates", 2, "result", "artifact", "candidate_id"
        )


@pytest.mark.asyncio
async def test_repeat_allocates_fresh_shared_owners_and_distinct_audio_identity() -> None:
    item = case()
    client = tts.FakeTTS([tts._response(), tts._response()])
    result = await runner(item, client).run(run_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED and len(client.calls) == 2
    ids = [
        value_at(s.typed_outputs, "candidates", 0, "result", "artifact", "candidate_id")
        for s in result.stage_results
    ]
    assert len(set(ids)) == 2


@pytest.mark.asyncio
async def test_cancel_collects_all_waiting_synthesis_calls() -> None:
    started, stopped = asyncio.Event(), []

    class Waiting(tts.FakeTTS):
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], parameters: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            self.calls.append((voice_ref, texts, parameters))
            if len(self.calls) == 2:
                started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(voice_ref)
            raise AssertionError("待機を通常終了へ読み替えてはなりません")

    item = case(accepted=True)
    client = Waiting([])
    lab = runner(item, client)
    work = asyncio.create_task(lab.run(run_spec(), item.fixture))
    await asyncio.wait_for(started.wait(), 1)
    await lab.cancel(run_spec().run_id)
    result = await work
    assert result.status is RunStatus.CANCELLED
    assert len(stopped) == 2 and lab.pending_count == 0


def test_duplicate_candidate_is_rejected_before_any_product_call() -> None:
    item = case()
    with pytest.raises(ValueError, match="異なる"):
        replace(item, inputs=(item.inputs[0], item.inputs[0]))


@pytest.mark.asyncio
async def test_provider_failure_preserves_other_candidate_result_and_releases_all_slots() -> None:
    from app.adapters.tts.contracts import TTSFailureCode
    from app.adapters.tts.provider import TTSProviderError

    item = case(accepted=True)
    client = tts.FakeTTS(
        [
            TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False),
            tts._response(),
        ]
    )
    result = await runner(item, client).run(run_spec(), item.fixture)
    assert result.status is RunStatus.PROVIDER_FAILED
    data = result.stage_results[0].typed_outputs
    assert value_at(data, "candidates", 0, "result", "failure_code") == "provider_rejected"
    assert value_at(data, "candidates", 2, "result", "artifact") is not None
    assert value_at(data, "admission_count_after_settlement") == 0
    assert value_at(data, "pending_task_count") == 0


@pytest.mark.asyncio
async def test_changed_input_does_not_invoke_provider() -> None:
    item = case()
    client = tts.FakeTTS([])
    changed = replace(item.fixture, typed_inputs={"different": True})
    result = await runner(item, client).run(run_spec(), changed)
    assert result.status is RunStatus.BLOCKED_UPSTREAM and client.calls == []


@pytest.mark.asyncio
async def test_lab_work_bound_is_checked_before_product_admission() -> None:
    item = case()
    client = tts.FakeTTS([])
    lab = ValidationRunner(
        (speech_capacity_target((item,), client, PROVENANCE, "1"),), replace(POLICY, max_tasks=4)
    )
    result = await lab.run(run_spec(), item.fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM and client.calls == []
