"""繰り返しの取消でも、提供先の回収と確定した効果を保持する。"""

import asyncio
from collections.abc import Sequence
from datetime import timedelta

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionCoordinator,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionPreflightSnapshot,
)
from app.domain.contracts import ExecutionStatus
from tests.domain.activity_execution.test_activity_execution import (
    NOW,
    Clock,
    effect,
    invocation,
    preflight,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("interruptibility", list(ActivityInterruptibility))
async def test_repeated_cancellation_reaps_provider_and_keeps_returned_effects(
    interruptibility: ActivityInterruptibility,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    cleanup_started = asyncio.Event()
    finished = asyncio.Event()
    cancellations = 0

    class Preflight:
        async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return preflight()

    class Port:
        async def execute(
            self,
            request: ExecutionDispatchRequest,
            cancellation: ExecutionCancellationSignal,
        ) -> Sequence[ExecutionAdapterReport]:
            nonlocal cancellations
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancellations += 1
                cleanup_started.set()
                await release.wait()
            finally:
                finished.set()
            assert cancellation.cancelled
            return (
                ExecutionAdapterReport(
                    request.invocation.command.command_id,
                    request.invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.COMPLETED,
                    NOW + timedelta(seconds=10),
                    {},
                    (effect("confirmed-after-cancel"),),
                ),
            )

    authority = ActivityExecutionAuthority()
    coordinator = ActivityExecutionCoordinator(Preflight(), Port(), authority, Clock())
    task = asyncio.create_task(coordinator.execute(invocation(interruptibility=interruptibility)))
    await started.wait()
    try:
        task.cancel()
        if interruptibility is ActivityInterruptibility.INTERRUPTIBLE:
            await asyncio.wait_for(cleanup_started.wait(), 1)
        else:
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done()
        await coordinator.cancel("command-1", "repeat_cancel")
        release.set()
        record = await asyncio.wait_for(task, 1)
        assert finished.is_set()
        assert record.result.status is ExecutionStatus.COMPLETED
        assert record.result.effect_refs == ("confirmed-after-cancel",)
        assert authority.snapshot("command-1") == record
        assert cancellations == (
            1 if interruptibility is ActivityInterruptibility.INTERRUPTIBLE else 0
        )
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
