"""本番の優先順位・容量制限と、待機時間の独立計測を確認する。"""

import asyncio
import json
from dataclasses import replace

import pytest

from app.domain.llm import (
    LLMFailureCode,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
)
from app.runtime.kernel import QueuePolicy, RuntimeWorkItem, WorkPriority
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.provider_scheduling import (
    ProviderSchedulingCase,
    provider_scheduling_target,
)
from app.subsystems.validation.runtime import ValidationRunner
from tests.adapters.llm.test_openai_responses import make_request
from tests.runtime.kernel import test_coordinator as kernel
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case(capacity: int = 4) -> ProviderSchedulingCase:
    template = kernel.item("normal", "provider")
    normal = RuntimeWorkItem(
        template.work_id,
        template.lane_id,
        make_request(),
        template.priority,
        template.revisions,
        template.created_at,
        template.queue_key,
        template.deadline_at,
        template.interruptible,
        template.shutdown_control,
    )
    urgent = replace(normal, work_id="urgent", priority=WorkPriority.CRITICAL)
    item = ProviderSchedulingCase(
        FIXTURE,
        (normal, urgent),
        (kernel.RuntimeLanePolicy("provider", capacity, QueuePolicy.REJECT_NEW),),
        kernel.TEST_SCHEDULER_POLICY,
        kernel.TEST_SHUTDOWN_POLICY,
    )
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


class Port:
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        await asyncio.sleep(0.01)
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.FAILED,
            request.revisions,
            request.created_at,
            request.trace_id,
            request.execution_policy.model_class,
            0,
            LLMTokenUsage(0, 0),
            failure=LLMRoleFailure(
                LLMFailureCode.PROVIDER_UNAVAILABLE,
                "試験用の利用不可",
                False,
            ),
        )


@pytest.mark.asyncio
async def test_runtime_priority_and_separate_wait_and_call_intervals() -> None:
    item = case()
    runner = ValidationRunner(
        (provider_scheduling_target((item,), Port(), PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(replace(spec(), target_module="provider_scheduling"), item.fixture)
    assert result.status is RunStatus.COMPLETED
    output = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"][0][
        "typed_outputs"
    ]
    values = output["measurements"]
    assert [x["work_id"] for x in values] == ["urgent", "normal"]
    assert all(x["provider_call_ns"] >= 10_000_000 for x in values)
    assert values[1]["admission_to_handler_ns"] >= values[0]["provider_call_ns"]
    assert not any(
        t.get_name().startswith("runtime-lane:") and not t.done() for t in asyncio.all_tasks()
    )


@pytest.mark.asyncio
async def test_queue_rejection_does_not_wait_for_nonexistent_outcome() -> None:
    item = case(1)
    runner = ValidationRunner(
        (provider_scheduling_target((item,), Port(), PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(replace(spec(), target_module="provider_scheduling"), item.fixture)
    assert result.status is RunStatus.COMPLETED
    output = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"][0][
        "typed_outputs"
    ]
    assert len(output["outcomes"]) == 1
    assert output["admissions"][1]["admission"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_displaced_work_is_not_waited_for() -> None:
    item = case(1)
    item = replace(item, lanes=(replace(item.lanes[0], queue_policy=QueuePolicy.DROP_OLDEST),))
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    runner = ValidationRunner(
        (provider_scheduling_target((item,), Port(), PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(replace(spec(), target_module="provider_scheduling"), item.fixture)
    assert result.status is RunStatus.COMPLETED
    output = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"][0][
        "typed_outputs"
    ]
    assert [x["work_id"] for x in output["outcomes"]] == ["urgent"]


@pytest.mark.asyncio
async def test_exception_duration_is_recorded_without_exporting_exception() -> None:
    class BrokenPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            raise RuntimeError("非公開の試験用接続情報")

    item = case()
    runner = ValidationRunner(
        (provider_scheduling_target((item,), BrokenPort(), PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(replace(spec(), target_module="provider_scheduling"), item.fixture)
    assert result.status is RunStatus.COMPLETED
    encoded = result.export_json(POLICY.max_export_bytes)
    assert "非公開" not in encoded
    output = json.loads(encoded)["stage_results"][0]["typed_outputs"]
    assert len(output["measurements"]) == 2
    assert all(x["provider_call_ns"] > 0 for x in output["measurements"])
    assert all(x["disposition"] == "failed" for x in output["outcomes"])


@pytest.mark.asyncio
async def test_cancel_reaps_scheduler_and_provider_call() -> None:
    started, stopped = asyncio.Event(), asyncio.Event()

    class WaitingPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            raise AssertionError("待機中の提供者が通常完了してはなりません")

    item = case()
    runner = ValidationRunner(
        (provider_scheduling_target((item,), WaitingPort(), PROVENANCE, "1"),), POLICY
    )
    task = asyncio.create_task(
        runner.run(replace(spec(), target_module="provider_scheduling"), item.fixture)
    )
    await asyncio.wait_for(started.wait(), 0.5)
    await runner.cancel(spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert stopped.is_set() and runner.pending_count == 0
    assert not any(
        t.get_name().startswith("runtime-") and not t.done() for t in asyncio.all_tasks()
    )
