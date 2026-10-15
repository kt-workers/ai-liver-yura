"""配置変更後も実際の実行カーネルの公開型・受付・取消・終了を維持する。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.domain.contracts.common import RevisionVector
from app.domain.contracts.lifecycle import ApplicationShutdownPolicy, ApplicationShutdownStage
from app.infrastructure import scheduling as legacy
from app.runtime import kernel
from app.runtime.kernel import (
    BoundedWorkQueue,
    CancellationRecord,
    CancellationRegistry,
    CancellationToken,
    CoordinatorState,
    LaneErrorPolicy,
    QueueAdmissionStatus,
    QueuePolicy,
    RuntimeCoordinator,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkDisposition,
    WorkPriority,
)

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


class Clock:
    """実時間を進めず、試験が指定した現在時刻だけを公開する。"""

    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current

    async def sleep(self, delay_seconds: float) -> None:
        self.current += timedelta(seconds=delay_seconds)
        await asyncio.sleep(0)


def item(
    work_id: str, *, lane: str = "main", priority: WorkPriority = WorkPriority.NORMAL,
    key: str | None = None, interruptible: bool = True,
) -> RuntimeWorkItem[object]:
    return RuntimeWorkItem(
        work_id, lane, object(), priority, RevisionVector(1), NOW,
        queue_key=key, interruptible=interruptible,
    )


def runtime(clock: Clock | None = None) -> RuntimeCoordinator:
    return RuntimeCoordinator(
        Clock() if clock is None else clock,
        RuntimeSchedulerPolicy("test-kernel", 1, 2),
        ApplicationShutdownPolicy("test-shutdown", 1, 1.0, 1.0, 1.0, 1.0),
    )


def lane(name: str = "main", *, limit: int = 1) -> RuntimeLanePolicy:
    return RuntimeLanePolicy(name, 8, QueuePolicy.REJECT_NEW, limit, 1.0, LaneErrorPolicy.ISOLATE)


@pytest.mark.parametrize("name", kernel.__all__)
def test_legacy_and_canonical_public_types_are_identical(name: str) -> None:
    assert getattr(legacy, name) is getattr(kernel, name)


@pytest.mark.parametrize(
    "policy,expected",
    [
        (QueuePolicy.REJECT_NEW, QueueAdmissionStatus.REJECTED),
        (QueuePolicy.DROP_OLDEST, QueueAdmissionStatus.DROPPED_OLDEST),
        (QueuePolicy.LATEST_WINS, QueueAdmissionStatus.REPLACED),
        (QueuePolicy.REPLACE_SAME_KEY, QueueAdmissionStatus.REPLACED),
        (QueuePolicy.COALESCE, QueueAdmissionStatus.COALESCED),
    ],
)
def test_all_queue_policies_preserve_displacement_and_capacity(
    policy: QueuePolicy, expected: QueueAdmissionStatus,
) -> None:
    queue: BoundedWorkQueue[object] = BoundedWorkQueue(
        1, policy, max_priority_burst=2,
        coalescer=(lambda _old, new: new) if policy is QueuePolicy.COALESCE else None,
    )
    first, second = item("first", key="same"), item("second", key="same")
    assert queue.put(first).accepted
    result = queue.put(second)
    assert result.status is expected
    assert len(queue) == 1
    if result.accepted:
        assert "first" in result.displaced_work_ids
        assert result.admitted_work_id == "second"
        assert queue.get() is second
    else:
        assert result.displaced_work_ids == ()
        assert queue.get() is first
    assert queue.get() is None


def test_fairness_debt_survives_priority_changes_and_shutdown_override() -> None:
    queue: BoundedWorkQueue[object] = BoundedWorkQueue(
        8, QueuePolicy.REJECT_NEW, max_priority_burst=2,
    )
    background = item("background", priority=WorkPriority.BACKGROUND)
    queue.put(background)
    for index, priority in enumerate((WorkPriority.CRITICAL, WorkPriority.FOREGROUND)):
        current = item(str(index), priority=priority)
        queue.put(current)
        assert queue.get() is current
    shutdown = replace(item("shutdown", priority=WorkPriority.CRITICAL), shutdown_control=True)
    queue.put(shutdown)
    assert queue.get() is shutdown
    ordinary_critical = item("critical", priority=WorkPriority.CRITICAL)
    queue.put(ordinary_critical)
    assert queue.get() is background
    assert queue.get() is ordinary_critical


def test_priority_fifo_does_not_skip_to_find_shutdown_marker() -> None:
    queue: BoundedWorkQueue[object] = BoundedWorkQueue(
        4, QueuePolicy.REJECT_NEW, max_priority_burst=1,
    )
    background = item("background", priority=WorkPriority.BACKGROUND)
    first = item("first", priority=WorkPriority.CRITICAL)
    second = item("second", priority=WorkPriority.CRITICAL)
    shutdown = replace(item("shutdown", priority=WorkPriority.CRITICAL), shutdown_control=True)
    for work in (background, first, second, shutdown):
        queue.put(work)
    assert [queue.get() for _ in range(4)] == [first, background, second, shutdown]


@pytest.mark.parametrize(
    "priority", [WorkPriority.FOREGROUND, WorkPriority.NORMAL, WorkPriority.BACKGROUND]
)
def test_shutdown_marker_does_not_turn_normal_work_into_control(priority: WorkPriority) -> None:
    with pytest.raises(ValueError, match="critical"):
        replace(item("invalid", priority=priority), shutdown_control=True)


@pytest.mark.asyncio
async def test_cancellation_identity_and_first_reason_are_preserved() -> None:
    registry = CancellationRegistry()
    token = registry.register("one")
    waiter = asyncio.create_task(token.wait())
    try:
        assert registry.cancel("one", "最初の取消", NOW)
        record = await asyncio.wait_for(waiter, 1.0)
        assert record is token.record
        assert not registry.cancel("one", "後の取消", NOW + timedelta(seconds=1))
        assert token.record == CancellationRecord("one", "最初の取消", NOW)
        registry.complete("one")
        assert registry.active_work_ids() == ()
        assert not registry.cancel("one", "完了後", NOW)
        with pytest.raises(ValueError):
            registry.register("one")
    finally:
        if not waiter.done():
            waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_slow_lane_does_not_block_other_lane_and_result_keeps_identity() -> None:
    value = runtime()
    entered, release = asyncio.Event(), asyncio.Event()
    result = object()

    async def slow(work: RuntimeWorkItem[object], cancellation: CancellationToken) -> object:
        entered.set()
        await release.wait()
        return work.payload

    async def fast(_work: RuntimeWorkItem[object], _cancellation: CancellationToken) -> object:
        return result

    value.register_lane(lane("slow"), slow)
    value.register_lane(lane("fast"), fast)
    await value.start()
    try:
        assert value.submit(item("slow", lane="slow")).accepted
        await asyncio.wait_for(entered.wait(), 1.0)
        assert value.submit(item("fast", lane="fast")).accepted
        outcome = await asyncio.wait_for(value.next_outcome(), 1.0)
        assert outcome.work_id == "fast"
        assert outcome.disposition is WorkDisposition.COMPLETED
        assert outcome.result is result
        assert not release.is_set()
    finally:
        release.set()
        await value.stop()
    assert value.state is CoordinatorState.STOPPED
    assert value.diagnostics().owned_task_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("interruptible", [True, False])
async def test_cancelled_work_never_publishes_success(interruptible: bool) -> None:
    value = runtime()
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(_work: RuntimeWorkItem[object], _cancellation: CancellationToken) -> str:
        entered.set()
        try:
            await release.wait()
            return "遅れて終了した結果"
        finally:
            finished.set()

    value.register_lane(lane(), handler)
    await value.start()
    try:
        assert value.submit(item("cancel", interruptible=interruptible)).accepted
        await asyncio.wait_for(entered.wait(), 1.0)
        assert value.cancel("cancel", "取消")
        assert not value.cancel("cancel", "再取消")
        if not interruptible:
            assert not finished.is_set()
        release.set()
        outcome = await asyncio.wait_for(value.next_outcome(), 1.0)
        assert outcome.disposition is WorkDisposition.CANCELLED
        assert finished.is_set()
    finally:
        release.set()
        await value.stop()
    assert value.diagnostics().owned_task_count == 0


@pytest.mark.asyncio
async def test_lane_limit_is_enforced_by_real_coordinator() -> None:
    value = runtime()
    entered, release = asyncio.Event(), asyncio.Event()
    active = 0
    maximum = 0

    async def handler(_work: RuntimeWorkItem[object], _cancellation: CancellationToken) -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 2:
            entered.set()
        try:
            await release.wait()
        finally:
            active -= 1

    value.register_lane(lane(limit=2), handler)
    await value.start()
    try:
        for index in range(5):
            assert value.submit(item(str(index))).accepted
        await asyncio.wait_for(entered.wait(), 1.0)
        assert active == 2
        assert value.diagnostics().lanes[0].queue_depth == 3
        release.set()
        for _ in range(5):
            outcome = await asyncio.wait_for(value.next_outcome(), 1.0)
            assert outcome.disposition is WorkDisposition.COMPLETED
    finally:
        release.set()
        await value.stop()
    assert maximum == 2
    assert value.diagnostics().owned_task_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_after_execution", [False, True])
async def test_stale_validation_runs_before_dispatch_and_before_publication(
    stale_after_execution: bool,
) -> None:
    value = runtime()
    fresh = stale_after_execution
    calls = 0

    async def handler(_work: RuntimeWorkItem[object], _cancellation: CancellationToken) -> None:
        nonlocal fresh, calls
        calls += 1
        fresh = False

    value.register_lane(lane(), handler, stale_validator=lambda _: fresh)
    await value.start()
    try:
        assert value.submit(item("stale")).accepted
        outcome = await asyncio.wait_for(value.next_outcome(), 1.0)
        assert outcome.disposition is WorkDisposition.STALE
        assert calls == int(stale_after_execution)
    finally:
        await value.stop()


@pytest.mark.asyncio
async def test_handler_failure_isolated_and_diagnostic_does_not_copy_payload() -> None:
    value = runtime()

    async def bad(_work: RuntimeWorkItem[object], _cancellation: CancellationToken) -> None:
        raise ValueError("診断へ出してはいけない入力本文")

    async def good(_work: RuntimeWorkItem[object], _cancellation: CancellationToken) -> int:
        return 17

    value.register_lane(lane("bad"), bad)
    value.register_lane(lane("good"), good)
    await value.start()
    try:
        value.submit(item("bad", lane="bad"))
        failed = await asyncio.wait_for(value.next_outcome(), 1.0)
        assert failed.disposition is WorkDisposition.FAILED
        assert failed.error == "ValueError"
        assert value.submit(item("good", lane="good")).accepted
        successful = await asyncio.wait_for(value.next_outcome(), 1.0)
        assert successful.result == 17
        assert successful.disposition is WorkDisposition.COMPLETED
        assert "診断へ出してはいけない入力本文" not in repr(value.diagnostics())
    finally:
        await value.stop()


@pytest.mark.asyncio
async def test_shutdown_flushes_before_reverse_resource_close_even_when_flush_fails() -> None:
    value = runtime()
    events: list[str] = []

    async def producer() -> None:
        events.append("producer")

    async def flush() -> None:
        events.append("flush")
        raise ValueError("最終保存の失敗")

    async def database() -> None:
        events.append("database")

    async def dependent() -> None:
        events.append("dependent")

    value.register_producer_stop_hook(producer)
    value.register_final_persistence_hook(flush)
    value.register_close_hook(database)
    value.register_close_hook(dependent)
    await value.start()
    await value.stop()
    await value.stop()
    assert events == ["producer", "flush", "dependent", "database"]
    assert value.state is CoordinatorState.STOPPED
    assert value.shutdown_failures[0].stage is ApplicationShutdownStage.FINAL_PERSISTENCE
    assert not value.submit(item("after-stop")).accepted
    assert value.diagnostics().owned_task_count == 0


@pytest.mark.asyncio
async def test_prestart_cancellation_reclaims_work_without_running_handler() -> None:
    class BeforeStartCoordinator(RuntimeCoordinator):
        def _work_done(self, lane: Any, work: RuntimeWorkItem[Any]) -> Any:
            callback = super()._work_done(lane, work)
            self._running_tasks[work.work_id].cancel()
            return callback

    value = BeforeStartCoordinator(
        Clock(), RuntimeSchedulerPolicy("test", 1, 2),
        ApplicationShutdownPolicy("shutdown", 1, 1, 1, 1, 1),
    )
    called = False

    async def handler(_work: RuntimeWorkItem[object], _cancellation: CancellationToken) -> None:
        nonlocal called
        called = True

    value.register_lane(lane(), handler)
    await value.start()
    try:
        assert value.submit(item("before-start")).accepted
        outcome = await asyncio.wait_for(value.next_outcome(), 1.0)
        assert outcome.disposition is WorkDisposition.CANCELLED
        assert not called
    finally:
        await value.stop()
    assert value.diagnostics().owned_task_count == 0
    assert value.diagnostics().lanes[0].in_flight == 0
