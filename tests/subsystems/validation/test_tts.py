"""本番の音声合成・再試行と公開参照への変換を確認する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.tts.contracts import TTSFailureCode
from app.adapters.tts.provider import (
    ProviderSynthesisInput,
    TTSProviderClient,
    TTSProviderError,
    TTSProviderResponse,
)
from app.subsystems.validation.contracts import Gate, LabRunSpec, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.tts import TTSSynthesisCase, tts_synthesis_target
from tests.adapters.tts import test_provider as tts
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case() -> TTSSynthesisCase:
    policy = tts._policy()
    item = TTSSynthesisCase(
        FIXTURE, tts._request(bundle=policy), policy.mapping, policy.operational, policy.retry
    )
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


def runner(item: TTSSynthesisCase, client: TTSProviderClient) -> ValidationRunner:
    return ValidationRunner((tts_synthesis_target((item,), client, PROVENANCE, "1"),), POLICY)


def run_spec(*, repeat_count: int = 1) -> LabRunSpec:
    return replace(spec(), target_module="tts_synthesis", repeat_count=repeat_count)


@pytest.mark.asyncio
async def test_real_mapping_retry_and_safe_audio_reference() -> None:
    item = case()
    client = tts.FakeTTS(
        [
            TTSProviderError(TTSFailureCode.PROVIDER_UNAVAILABLE, True),
            tts._response(raw_audio_ref="private-provider-resource"),
        ]
    )
    result = await runner(item, client).run(run_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    output = value_at(result.stage_results[0].typed_outputs, "result")
    assert value_at(output, "attempts") == 2 and value_at(output, "artifact") is not None
    assert len(client.calls) == 2 and client.calls[0][2].segments
    assert "private-provider-resource" not in result.export_json(POLICY.max_export_bytes)


@pytest.mark.asyncio
async def test_failed_provider_retains_typed_failure_without_raw_exception() -> None:
    item = case()
    client = tts.FakeTTS([TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False)])
    result = await runner(item, client).run(run_spec(), item.fixture)
    assert result.status is RunStatus.PROVIDER_FAILED
    assert (
        value_at(result.stage_results[0].typed_outputs, "result", "failure_code")
        == "provider_rejected"
    )
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_repeat_artifacts_are_candidate_local() -> None:
    item = case()
    client = tts.FakeTTS([tts._response(), tts._response()])
    result = await runner(item, client).run(run_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert (
        len(
            {
                value_at(s.typed_outputs, "result", "artifact", "candidate_id")
                for s in result.stage_results
            }
        )
        == 2
    )


@pytest.mark.asyncio
async def test_cancel_reaps_provider_call() -> None:
    item = case()
    started, stopped = asyncio.Event(), asyncio.Event()

    class WaitingClient:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], provider_input: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            raise AssertionError("待機中の音声合成が通常完了してはなりません")

    lab = runner(item, WaitingClient())
    task = asyncio.create_task(lab.run(run_spec(), item.fixture))
    await asyncio.wait_for(started.wait(), 0.5)
    await lab.cancel(run_spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert stopped.is_set() and lab.pending_count == 0


@pytest.mark.asyncio
async def test_provider_result_after_deadline_is_not_accepted() -> None:
    item = case()
    request = replace(
        item.request, deadline_at=item.request.created_at + timedelta(milliseconds=20)
    )
    item = replace(item, request=request)
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))

    class SlowClient:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], provider_input: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            await asyncio.sleep(0.03)
            return tts._response()

    result = await runner(item, SlowClient()).run(run_spec(), item.fixture)
    assert result.status is RunStatus.TIMED_OUT
    output = value_at(result.stage_results[0].typed_outputs, "result")
    assert (
        value_at(output, "artifact") is None
        and value_at(output, "failure_code") == "request_timeout"
    )
