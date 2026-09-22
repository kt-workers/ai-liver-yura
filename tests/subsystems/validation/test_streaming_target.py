"""配信の型付き実行・効果の不確かさ・取消時の回収を製品入口で確認する。"""

import asyncio
import json
from dataclasses import replace
from typing import NoReturn

import pytest

from app.subsystems.streaming.contracts import StreamingExecutionRequest, StreamingOperation
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.streaming import StreamingLabCase, streaming_target
from tests.subsystems.streaming import test_runtime as streaming
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case(*, available: bool = True) -> StreamingLabCase:
    item = StreamingLabCase(
        FIXTURE,
        streaming.capability(available=available),
        tuple(streaming.request(operation) for operation in StreamingOperation),
        streaming.NOW,
    )
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


@pytest.mark.asyncio
async def test_all_operations_keep_actual_provider_reports() -> None:
    item, provider = case(), streaming.Provider()
    target = streaming_target((item,), provider, PROVENANCE, "1")
    runner = ValidationRunner((target,), replace(POLICY, max_intervals=64))
    result = await runner.run(
        replace(spec(), target_module="streaming", repeat_count=2), item.fixture
    )
    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 2 * len(StreamingOperation)
    assert len({x.execution_id for x in provider.calls}) == len(provider.calls)
    stages = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    for stage in stages:
        assert all(x["effect_state"] == "applied" for x in stage["typed_outputs"]["reports"])
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [False, True])
async def test_pre_admission_failure_and_provider_failure_keep_distinct_effects(
    available: bool,
) -> None:
    item, provider = case(available=available), streaming.Provider(unavailable=True)
    target = streaming_target((item,), provider, PROVENANCE, "1")
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="streaming"), item.fixture
    )
    assert result.status is RunStatus.PROVIDER_FAILED
    output = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"][0][
        "typed_outputs"
    ]
    assert output["reports"][0]["effect_state"] == ("unknown" if available else "not_applied")
    assert len(provider.calls) == int(available)


@pytest.mark.asyncio
async def test_cancel_collects_waiting_provider() -> None:
    started, stopped = asyncio.Event(), asyncio.Event()

    class Provider:
        async def execute(self, request: StreamingExecutionRequest) -> NoReturn:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            raise AssertionError("待機中の配信処理が通常完了してはなりません")

    item = case()
    runner = ValidationRunner((streaming_target((item,), Provider(), PROVENANCE, "1"),), POLICY)
    task = asyncio.create_task(runner.run(replace(spec(), target_module="streaming"), item.fixture))
    await asyncio.wait_for(started.wait(), 0.5)
    await runner.cancel(spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED and stopped.is_set()
    assert runner.pending_count == 0
