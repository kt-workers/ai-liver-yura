"""判断の本体実行への登録と相関照合・並行動作・停止を検証する。"""

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from app.composition.executive import ExecutiveBrainModulePort, ExecutiveBrainWorkPayload
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
    BrainWorkEnvelope,
    BrainWorkPriority,
    BrainWorkStatus,
)
from app.runtime.kernel import CancellationToken
from tests.domain.brain_integration.test_runtime import FakePort, policy
from tests.system_integration.test_core_attention import offer_user
from tests.system_integration.test_core_executive import wired


def work(value: Any) -> BrainIntegrationWork:
    dispatch = value.dispatch
    return BrainIntegrationWork(
        "executive",
        BrainIntegrationModule.EXECUTIVE,
        BrainIntegrationLane.COGNITIVE_NORMAL,
        BrainWorkEnvelope(
            "trace:runtime",
            dispatch.trigger.trigger_id,
            ("event:1",),
            dispatch.reference.context.source_context_revision,
            dispatch.reference.goals.goal_revision,
            dispatch.trigger.attention_revision,
            BrainWorkPriority.NORMAL,
            value.core.clock.now(),
        ),
        ExecutiveBrainWorkPayload(dispatch, "request:runtime", "decision:runtime"),
    )


def runtime_for(value: Any) -> BrainIntegrationRuntime:
    runtime = BrainIntegrationRuntime(value.core.clock, policy())
    runtime.register_module(
        BrainIntegrationModule.EXECUTIVE, ExecutiveBrainModulePort(value.binding)
    )
    return runtime


@pytest.mark.asyncio
async def test_judgment_wait_allows_foreground_and_returns_committed_result() -> None:
    value = wired()
    value.llm.release.clear()
    runtime = runtime_for(value)
    runtime.register_module(BrainIntegrationModule.INPUT_MEANING, FakePort("別の入力"))
    await runtime.start()
    try:
        item = work(value)
        assert runtime.submit(item).accepted
        await asyncio.wait_for(value.llm.started.wait(), 1)
        foreground = replace(
            item, work_id="foreground", module=BrainIntegrationModule.INPUT_MEANING,
            lane=BrainIntegrationLane.FOREGROUND_INTERACTION,
        )
        assert runtime.submit(foreground).accepted
        outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
        assert outcome.work_id == "foreground"
        assert outcome.result == "別の入力"
        assert value.binding.latest_decision() is None
        value.llm.release.set()
        outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
        assert outcome.status is BrainWorkStatus.COMPLETED
        assert outcome.result is value.binding.latest_decision()
        assert value.llm.requests[0].trace_id == item.envelope.trace_id
    finally:
        value.llm.release.set()
        await runtime.stop()


@pytest.mark.parametrize("field", [
    "trigger_id", "source_context_revision", "goal_revision", "attention_revision",
])
def test_mismatched_correlation_is_rejected_before_judgment(field: str) -> None:
    value = wired()
    item = work(value)
    invalid = {
        "trigger_id": replace(item.envelope, trigger_id="wrong"),
        "source_context_revision": replace(item.envelope, source_context_revision=999),
        "goal_revision": replace(item.envelope, goal_revision=999),
        "attention_revision": replace(item.envelope, attention_revision=999),
    }
    item = replace(item, envelope=invalid[field])
    with pytest.raises(ValueError, match="一致しません"):
        ExecutiveBrainModulePort(value.binding).is_fresh(item)
    assert not value.llm.requests


@pytest.mark.asyncio
async def test_wrong_source_events_fail_without_calling_llm() -> None:
    value = wired()
    item = work(value)
    item = replace(item, envelope=replace(item.envelope, source_event_ids=("other",)))
    with pytest.raises(ValueError, match="元イベント"):
        await ExecutiveBrainModulePort(value.binding).execute(item, CancellationToken())
    assert not value.llm.requests
    assert value.binding.latest_decision() is None


@pytest.mark.asyncio
async def test_stale_attention_is_not_executed_by_runtime() -> None:
    value = wired()
    runtime = runtime_for(value)
    offer_user(value.attention_owner, value.core)
    await runtime.start()
    try:
        assert runtime.submit(work(value)).accepted
        outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
        assert outcome.status is BrainWorkStatus.STALE
        assert not value.llm.requests
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_stop_reaps_judgment_without_committing_and_preserves_outcome() -> None:
    value = wired()
    value.llm.release.clear()
    runtime = runtime_for(value)
    before = asyncio.all_tasks()
    await runtime.start()
    assert runtime.submit(work(value)).accepted
    await asyncio.wait_for(value.llm.started.wait(), 1)
    await runtime.stop()
    outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
    assert outcome.status is BrainWorkStatus.CANCELLED
    assert value.binding.latest_decision() is None
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
    assert not (asyncio.all_tasks() - before)


@pytest.mark.asyncio
async def test_queue_limit_remains_owned_by_runtime() -> None:
    value = wired()
    value.llm.release.clear()
    runtime = runtime_for(value)
    await runtime.start()
    try:
        item = work(value)
        assert runtime.submit(item).accepted
        await asyncio.wait_for(value.llm.started.wait(), 1)
        for number in range(4):
            assert runtime.submit(replace(item, work_id=f"queued:{number}")).accepted
        assert not runtime.submit(replace(item, work_id="overflow")).accepted
        assert len(value.llm.requests) == 1
    finally:
        await runtime.stop()
    assert value.binding.latest_decision() is None


@pytest.mark.parametrize("field", ["request_id", "decision_id"])
def test_empty_identifiers_are_rejected(field: str) -> None:
    value = wired()
    item = work(value)
    assert isinstance(item.payload, ExecutiveBrainWorkPayload)
    invalid = {
        "request_id": replace(item.payload, request_id=""),
        "decision_id": replace(item.payload, decision_id=""),
    }
    item = replace(item, payload=invalid[field])
    with pytest.raises(ValueError):
        ExecutiveBrainModulePort(value.binding).is_fresh(item)


@pytest.mark.asyncio
async def test_runtime_reports_invalid_evidence_as_failure() -> None:
    value = wired()
    runtime = runtime_for(value)
    await runtime.start()
    try:
        item = work(value)
        item = replace(item, envelope=replace(item.envelope, source_event_ids=("other",)))
        assert runtime.submit(item).accepted
        outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
        assert outcome.status is BrainWorkStatus.FAILED
        assert outcome.error == "ValueError"
        assert not value.llm.requests
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_direct_binding_rejects_conflicting_trace_before_creating_work() -> None:
    value = wired()
    before = asyncio.all_tasks()
    with pytest.raises(ValueError, match="追跡識別子"):
        await value.binding.deliberate(
            value.dispatch, request_id="request", trace_id="other", decision_id="decision",
            cancellation=CancellationToken(), envelope=work(value).envelope,
        )
    assert not value.llm.requests
    assert asyncio.all_tasks() == before
