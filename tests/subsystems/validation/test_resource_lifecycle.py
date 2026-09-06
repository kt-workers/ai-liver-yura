"""検証が生成した接続資源を、成功・取消・終了失敗時にも回収する。"""

import asyncio
from dataclasses import replace

import pytest

from app.subsystems.validation.contracts import (
    Gate,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, spec, target


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_owned_resources_close_after_children_and_only_once(cancel: bool) -> None:
    started, released = asyncio.Event(), asyncio.Event()
    order: list[str] = []
    contexts: list[RunContext] = []

    async def child() -> None:
        started.set()
        try:
            await released.wait()
        finally:
            order.append("child")

    async def close() -> None:
        assert order == ["child"]
        order.append("resource")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        contexts.append(context)
        context.add_cleanup("client", close)
        context.spawn("waiting", child)
        await started.wait()
        if not cancel:
            released.set()
        await context.settle()
        return TargetObservation(RunStatus.COMPLETED, Gate.NOT_RUN, None)

    runner = ValidationRunner((replace(target(), run=run),), POLICY)
    task = asyncio.create_task(runner.run(spec(), FIXTURE))
    await asyncio.wait_for(started.wait(), 0.5)
    if cancel:
        await runner.cancel(spec().run_id)
    result = await task
    assert result.status is (RunStatus.CANCELLED if cancel else RunStatus.COMPLETED)
    assert order == ["child", "resource"]
    await contexts[0].close()
    assert order == ["child", "resource"]
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel", "timeout"])
async def test_cleanup_failure_does_not_skip_other_resources_or_expose_details(
    failure: str,
) -> None:
    order: list[str] = []

    async def first() -> None:
        order.append("first")

    async def broken() -> None:
        order.append("broken")
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "timeout":
            await asyncio.Event().wait()
        raise RuntimeError("非公開のクライアント終了情報")

    async def last() -> None:
        order.append("last")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        context.add_cleanup("first", first)
        context.add_cleanup("broken", broken)
        context.add_cleanup("last", last)
        return TargetObservation(RunStatus.COMPLETED, Gate.PASS, None)

    policy = replace(POLICY, timeout_seconds=0.05)
    runner = ValidationRunner((replace(target(), run=run),), policy)
    result = await runner.run(spec(), FIXTURE)
    assert result.status is RunStatus.HARNESS_FAILED and result.machine_gate is Gate.NOT_RUN
    assert order == ["last", "broken", "first"]
    assert "非公開の" not in result.export_json(policy.max_export_bytes)
    assert runner.pending_count == 0
