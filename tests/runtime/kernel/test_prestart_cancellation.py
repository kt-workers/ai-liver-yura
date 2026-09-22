"""実行taskの開始前取消でも、Kernelが自身の管理記録と結果を回収する。"""

import asyncio

import pytest

from app.runtime.kernel import FakeRuntimeClock, QueuePolicy, RuntimeHealth, WorkDisposition
from tests.runtime.kernel.test_coordinator import (
    NOW,
    RuntimeCoordinator,
    RuntimeLanePolicy,
    item,
)


@pytest.mark.parametrize("stop_directly", [False, True])
def test_prestart_cancellation_reaps_once_and_shutdown_completes(stop_directly: bool) -> None:
    async def scenario() -> None:
        for _ in range(3):
            calls = 0

            async def handler(work: object, token: object) -> None:
                nonlocal calls
                calls += 1

            runtime = RuntimeCoordinator(FakeRuntimeClock(NOW))
            runtime.register_lane(RuntimeLanePolicy("test", 2, QueuePolicy.REJECT_NEW), handler)
            await runtime.start()
            runtime.submit(item("before-start", "test"))
            # workerだけを進め、生成された実行taskの最初の命令より前に取消する。
            await asyncio.sleep(0)
            assert calls == 0
            if not stop_directly:
                assert runtime.cancel("before-start", "開始前取消")
                runtime.cancel("before-start", "再取消")
            await runtime.stop()
            outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
            assert outcome.disposition is WorkDisposition.CANCELLED
            assert calls == 0
            diagnostics = runtime.diagnostics()
            assert diagnostics.health is RuntimeHealth.STOPPED
            assert diagnostics.owned_task_count == 0
            lane = diagnostics.lanes[0]
            assert lane.in_flight == lane.queue_depth == 0
            assert lane.cancelled == 1
            assert not runtime.cancel("before-start", "回収後")
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(runtime.next_outcome(), 0.01)
            await runtime.stop()

    asyncio.run(scenario())
