"""Brainの単一結果pump・終端通知・停止所有権を検証する。"""

import asyncio
from dataclasses import replace

import pytest

from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainWorkStatus,
)
from app.domain.brain_integration.runtime import BrainIntegrationWork, BrainIntegrationWorkOutcome
from app.runtime.kernel import FakeRuntimeClock, QueuePolicy
from tests.domain.brain_integration.test_runtime import NOW, FakePort, policy, work


@pytest.mark.asyncio
async def test_synthetic_and_kernel_publish_observer_once_before_consumption() -> None:
    config = policy()
    config = replace(
        config,
        lane_policies=tuple(
            replace(p, queue_capacity=1, queue_policy=QueuePolicy.DROP_OLDEST)
            for p in config.lane_policies
        ),
    )
    runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), config)
    seen: list[BrainIntegrationWorkOutcome] = []

    def observed(original: BrainIntegrationWork, outcome: BrainIntegrationWorkOutcome) -> None:
        assert outcome.work_id == original.work_id
        seen.append(outcome)

    runtime.register_module(BrainIntegrationModule.INPUT_MEANING, FakePort("meaning"))
    runtime.register_terminal_observer(BrainIntegrationModule.INPUT_MEANING, observed)
    runtime.register_terminal_observer(BrainIntegrationModule.MEMORY, observed)
    await runtime.start()
    try:
        with pytest.raises(RuntimeError):
            runtime.register_terminal_observer(BrainIntegrationModule.EXECUTIVE, observed)
        first = work(
            "first",
            BrainIntegrationModule.INPUT_MEANING,
            BrainIntegrationLane.FOREGROUND_INTERACTION,
        )
        assert runtime.submit(first).accepted
        assert runtime.submit(replace(first, work_id="second")).accepted
        assert not runtime.submit(
            replace(first, work_id="missing", module=BrainIntegrationModule.MEMORY)
        ).accepted
        await runtime.stop()
        assert len(seen) == 3
        assert len({o.work_id for o in seen}) == 3
        assert next(o for o in seen if o.work_id == "first").status is BrainWorkStatus.SUPERSEDED
        assert next(o for o in seen if o.work_id == "missing").status is BrainWorkStatus.REJECTED
        published = [await runtime.next_outcome() for _ in range(3)]
        assert published == seen
        with pytest.raises(RuntimeError):
            runtime.submit(replace(first, work_id="after-stop"))
    finally:
        await runtime.stop()
    assert runtime._pump_task is not None and runtime._pump_task.done()
    assert not runtime._pending_runtime


@pytest.mark.asyncio
async def test_observer_failure_preserves_outcome_and_drains_other_work() -> None:
    runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
    seen: list[str] = []

    def observer(original: BrainIntegrationWork, outcome: BrainIntegrationWorkOutcome) -> None:
        seen.append(original.work_id)
        if original.work_id == "first":
            raise ValueError("通知先の故障")

    runtime.register_module(BrainIntegrationModule.INPUT_MEANING, FakePort("meaning"))
    runtime.register_terminal_observer(BrainIntegrationModule.INPUT_MEANING, observer)
    await runtime.start()
    first = work(
        "first", BrainIntegrationModule.INPUT_MEANING, BrainIntegrationLane.FOREGROUND_INTERACTION
    )
    assert runtime.submit(first).accepted
    assert runtime.submit(replace(first, work_id="second")).accepted
    outcomes = [await asyncio.wait_for(runtime.next_outcome(), 2) for _ in range(2)]
    assert all(o.status is BrainWorkStatus.COMPLETED for o in outcomes)
    assert sorted(seen) == ["first", "second"]
    with pytest.raises(RuntimeError, match="受付可能"):
        runtime.submit(replace(first, work_id="third"))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="observer"):
            await runtime.stop()
    assert not runtime._pending_runtime
    assert runtime._pump_task is not None and runtime._pump_task.done()


@pytest.mark.asyncio
async def test_cancelled_stop_caller_still_reaps_pump_and_execution() -> None:
    runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
    entered = asyncio.Event()
    runtime.register_module(
        BrainIntegrationModule.INPUT_MEANING,
        FakePort("meaning", gate=asyncio.Event(), started=entered),
    )
    seen: list[str] = []
    runtime.register_terminal_observer(
        BrainIntegrationModule.INPUT_MEANING, lambda w, o: seen.append(w.work_id)
    )
    await runtime.start()
    runtime.submit(
        work(
            "slow",
            BrainIntegrationModule.INPUT_MEANING,
            BrainIntegrationLane.FOREGROUND_INTERACTION,
        )
    )
    await entered.wait()
    caller = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    await runtime.stop()
    assert seen == ["slow"]
    assert runtime._pump_task is not None and runtime._pump_task.done()
    assert runtime._runtime.diagnostics().owned_task_count == 0


@pytest.mark.parametrize("instance", [False, True])
def test_async_terminal_observer_is_rejected_before_start(instance: bool) -> None:
    async def observer(work: BrainIntegrationWork, outcome: BrainIntegrationWorkOutcome) -> None:
        pass

    class Observer:
        async def __call__(
            self, work: BrainIntegrationWork, outcome: BrainIntegrationWorkOutcome
        ) -> None:
            pass

    runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
    # 型違反をする登録元を再現し、呼出前に拒否されることを確認する。
    from typing import Any

    invalid: Any = Observer() if instance else observer
    with pytest.raises(ValueError, match="登録が不正"):
        runtime.register_terminal_observer(BrainIntegrationModule.INPUT_MEANING, invalid)
