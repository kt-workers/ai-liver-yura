import asyncio
from datetime import datetime, timedelta, timezone

from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    FakeRuntimeClock,
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeHealth,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkDisposition,
    WorkPriority,
)
from app.runtime.kernel import (
    RuntimeCoordinator as KernelRuntimeCoordinator,
)
from app.runtime.kernel import (
    RuntimeLanePolicy as KernelRuntimeLanePolicy,
)
from app.runtime.shutdown import RuntimeShutdownPolicy

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
TEST_SCHEDULER_POLICY = RuntimeSchedulerPolicy("test.scheduler", 1, 8)
TEST_SHUTDOWN_POLICY = RuntimeShutdownPolicy("test.shutdown", 1, 1.0, 1.0, 1.0, 1.0)


def RuntimeCoordinator(clock: FakeRuntimeClock) -> KernelRuntimeCoordinator:
    return KernelRuntimeCoordinator(clock, TEST_SCHEDULER_POLICY, TEST_SHUTDOWN_POLICY)


def RuntimeLanePolicy(
    lane_id: str,
    queue_capacity: int,
    queue_policy: QueuePolicy,
    *,
    max_in_flight: int = 1,
    cancellation_grace_seconds: float = 1.0,
    error_policy: LaneErrorPolicy = LaneErrorPolicy.ISOLATE,
) -> KernelRuntimeLanePolicy:
    return KernelRuntimeLanePolicy(
        lane_id,
        queue_capacity,
        queue_policy,
        max_in_flight,
        cancellation_grace_seconds,
        error_policy,
    )


def item(work_id: str, lane: str, *, deadline_seconds: int | None = None) -> RuntimeWorkItem[str]:
    return RuntimeWorkItem(
        work_id,
        lane,
        work_id,
        WorkPriority.NORMAL,
        RevisionVector(1),
        NOW,
        deadline_at=None
        if deadline_seconds is None
        else NOW + timedelta(seconds=deadline_seconds),
    )


def test_slow_lane_does_not_block_unrelated_lane_and_shutdown_leaves_no_tasks() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        slow_gate = asyncio.Event()

        async def slow_handler(work: RuntimeWorkItem[object], _token: object) -> str:
            await slow_gate.wait()
            return str(work.payload)

        async def fast_handler(work: RuntimeWorkItem[object], _token: object) -> str:
            return str(work.payload)

        coordinator = RuntimeCoordinator(clock)
        coordinator.register_lane(
            RuntimeLanePolicy("reflection", 4, QueuePolicy.REJECT_NEW), slow_handler
        )
        coordinator.register_lane(
            RuntimeLanePolicy("foreground", 4, QueuePolicy.REJECT_NEW), fast_handler
        )
        await coordinator.start()
        coordinator.submit(item("slow", "reflection"))
        coordinator.submit(item("fast", "foreground"))
        outcome = await coordinator.next_outcome()
        assert outcome.work_id == "fast"
        assert outcome.disposition is WorkDisposition.COMPLETED
        slow_gate.set()
        assert (await coordinator.next_outcome()).work_id == "slow"
        await coordinator.stop()
        assert coordinator.diagnostics().owned_task_count == 0
        assert coordinator.diagnostics().health is RuntimeHealth.STOPPED
        await coordinator.stop()

    asyncio.run(scenario())


def test_lane_max_in_flight_and_cancellation() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        gate = asyncio.Event()
        started: list[str] = []

        async def handler(work: RuntimeWorkItem[object], _token: object) -> str:
            started.append(work.work_id)
            await gate.wait()
            return work.work_id

        coordinator = RuntimeCoordinator(clock)
        coordinator.register_lane(
            RuntimeLanePolicy("lane", 4, QueuePolicy.REJECT_NEW, max_in_flight=1),
            handler,
        )
        await coordinator.start()
        coordinator.submit(item("one", "lane"))
        coordinator.submit(item("two", "lane"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert started == ["one"]
        assert coordinator.cancel("one", "interrupt")
        assert (await coordinator.next_outcome()).disposition is WorkDisposition.CANCELLED
        await asyncio.sleep(0)
        gate.set()
        assert (await coordinator.next_outcome()).work_id == "two"
        await coordinator.stop()

    asyncio.run(scenario())


def test_stale_deadline_and_error_are_isolated_and_diagnosed() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW + timedelta(seconds=2))

        async def handler(work: RuntimeWorkItem[object], _token: object) -> str:
            if work.work_id == "bad":
                raise RuntimeError("isolated")
            return work.work_id

        coordinator = RuntimeCoordinator(clock)
        coordinator.register_lane(
            RuntimeLanePolicy("lane", 8, QueuePolicy.REJECT_NEW, max_in_flight=3),
            handler,
            stale_validator=lambda work: work.work_id != "stale",
        )
        await coordinator.start()
        coordinator.submit(item("expired", "lane", deadline_seconds=1))
        coordinator.submit(item("stale", "lane"))
        coordinator.submit(item("bad", "lane"))
        coordinator.submit(item("good", "lane"))
        outcomes = {
            outcome.work_id: outcome
            for outcome in [
                await coordinator.next_outcome(),
                await coordinator.next_outcome(),
                await coordinator.next_outcome(),
                await coordinator.next_outcome(),
            ]
        }
        assert outcomes["expired"].disposition is WorkDisposition.TIMED_OUT
        assert outcomes["stale"].disposition is WorkDisposition.STALE
        assert outcomes["bad"].disposition is WorkDisposition.FAILED
        assert outcomes["good"].disposition is WorkDisposition.COMPLETED
        assert coordinator.diagnostics().health is RuntimeHealth.DEGRADED
        await coordinator.stop()

    asyncio.run(scenario())


def test_post_stop_admission_is_rejected() -> None:
    async def scenario() -> None:
        coordinator = RuntimeCoordinator(FakeRuntimeClock(NOW))
        await coordinator.start()
        await coordinator.stop()
        assert not coordinator.submit(item("late", "missing")).accepted

    asyncio.run(scenario())


def test_coalesced_admission_registers_actual_combined_work_identity() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        gate = asyncio.Event()

        async def handler(work: RuntimeWorkItem[object], _token: object) -> str:
            await gate.wait()
            return work.work_id

        def combine(
            old: RuntimeWorkItem[object], new: RuntimeWorkItem[object]
        ) -> RuntimeWorkItem[object]:
            return RuntimeWorkItem(
                new.work_id,
                old.lane_id,
                (old.payload, new.payload),
                old.priority,
                old.revisions,
                old.created_at,
                old.queue_key,
            )

        coordinator = RuntimeCoordinator(clock)
        coordinator.register_lane(
            RuntimeLanePolicy("lane", 2, QueuePolicy.COALESCE),
            handler,
            coalescer=combine,
        )
        await coordinator.start()
        first = RuntimeWorkItem(
            "one", "lane", "one", WorkPriority.NORMAL, RevisionVector(1), NOW, "same"
        )
        second = RuntimeWorkItem(
            "two", "lane", "two", WorkPriority.NORMAL, RevisionVector(1), NOW, "same"
        )
        coordinator.submit(first)
        admission = coordinator.submit(second)
        assert admission.admitted_work_id == "two"
        await asyncio.sleep(0)
        gate.set()
        assert (await coordinator.next_outcome()).work_id == "two"
        await coordinator.stop()

    asyncio.run(scenario())


def test_cross_lane_duplicate_running_work_id_is_rejected_atomically() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()

        async def handler(work: RuntimeWorkItem[object], _token: object) -> str:
            await gate.wait()
            return work.work_id

        coordinator = RuntimeCoordinator(FakeRuntimeClock(NOW))
        coordinator.register_lane(
            RuntimeLanePolicy("a", 2, QueuePolicy.REJECT_NEW), handler
        )
        coordinator.register_lane(
            RuntimeLanePolicy("b", 2, QueuePolicy.REJECT_NEW), handler
        )
        await coordinator.start()
        assert coordinator.submit(item("same", "a")).accepted
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not coordinator.submit(item("same", "b")).accepted
        diagnostics = {lane.lane_id: lane for lane in coordinator.diagnostics().lanes}
        assert diagnostics["b"].queue_depth == 0
        gate.set()
        await coordinator.next_outcome()
        await coordinator.stop()

    asyncio.run(scenario())


def test_non_interruptible_running_work_uses_soft_cancellation() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        hard_cancelled = False

        async def handler(work: RuntimeWorkItem[object], _token: object) -> str:
            nonlocal hard_cancelled
            try:
                await gate.wait()
            except asyncio.CancelledError:
                hard_cancelled = True
                raise
            return work.work_id

        coordinator = RuntimeCoordinator(FakeRuntimeClock(NOW))
        coordinator.register_lane(
            RuntimeLanePolicy("lane", 2, QueuePolicy.REJECT_NEW), handler
        )
        await coordinator.start()
        work = RuntimeWorkItem(
            "soft",
            "lane",
            "soft",
            WorkPriority.NORMAL,
            RevisionVector(1),
            NOW,
            interruptible=False,
        )
        coordinator.submit(work)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert coordinator.cancel("soft", "superseded")
        await asyncio.sleep(0)
        assert not hard_cancelled
        gate.set()
        outcome = await coordinator.next_outcome()
        assert outcome.disposition is WorkDisposition.CANCELLED
        await coordinator.stop()

    asyncio.run(scenario())


def test_diagnostics_never_include_exception_message() -> None:
    async def scenario() -> None:
        async def handler(_work: RuntimeWorkItem[object], _token: object) -> str:
            raise RuntimeError("secret-token-and-payload")

        coordinator = RuntimeCoordinator(FakeRuntimeClock(NOW))
        coordinator.register_lane(
            RuntimeLanePolicy("lane", 1, QueuePolicy.REJECT_NEW), handler
        )
        await coordinator.start()
        coordinator.submit(item("bad", "lane"))
        outcome = await coordinator.next_outcome()
        assert outcome.error == "RuntimeError"
        assert coordinator.diagnostics().lanes[0].last_error == "RuntimeError"
        await coordinator.stop()

    asyncio.run(scenario())


def test_stop_runs_close_hook_and_accepts_only_shutdown_control_while_stopping() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        stopping = asyncio.Event()
        closed: list[str] = []

        async def handler(work: RuntimeWorkItem[object], _token: object) -> str:
            if work.work_id == "running":
                stopping.set()
                await gate.wait()
            return work.work_id

        async def close_resource() -> None:
            closed.append("closed")

        coordinator = RuntimeCoordinator(FakeRuntimeClock(NOW))
        coordinator.register_lane(
            RuntimeLanePolicy(
                "lane",
                4,
                QueuePolicy.REJECT_NEW,
                cancellation_grace_seconds=0.1,
            ),
            handler,
        )
        coordinator.register_close_hook(close_resource)
        await coordinator.start()
        running = RuntimeWorkItem(
            "running",
            "lane",
            "running",
            WorkPriority.NORMAL,
            RevisionVector(1),
            NOW,
            interruptible=False,
        )
        coordinator.submit(running)
        await stopping.wait()
        stop_task = asyncio.create_task(coordinator.stop())
        await asyncio.sleep(0)
        assert coordinator.state.value == "stopping"
        assert not coordinator.submit(item("normal-late", "lane")).accepted
        control = RuntimeWorkItem(
            "shutdown-control",
            "lane",
            "close",
            WorkPriority.CRITICAL,
            RevisionVector(1),
            NOW,
            shutdown_control=True,
        )
        assert coordinator.submit(control).accepted
        gate.set()
        await stop_task
        assert closed == ["closed"]
        assert coordinator.diagnostics().owned_task_count == 0

    asyncio.run(scenario())


def test_shutdown_control_is_rejected_after_admission_gate_closes() -> None:
    async def scenario() -> None:
        close_started = asyncio.Event()
        close_gate = asyncio.Event()
        handled: list[str] = []

        async def handler(work: RuntimeWorkItem[object], _token: object) -> str:
            handled.append(work.work_id)
            return work.work_id

        async def close_resource() -> None:
            close_started.set()
            await close_gate.wait()

        coordinator = RuntimeCoordinator(FakeRuntimeClock(NOW))
        coordinator.register_lane(
            RuntimeLanePolicy("lane", 2, QueuePolicy.REJECT_NEW), handler
        )
        coordinator.register_close_hook(close_resource)
        await coordinator.start()
        stop_task = asyncio.create_task(coordinator.stop())
        await close_started.wait()
        late_control = RuntimeWorkItem(
            "late-control",
            "lane",
            "close",
            WorkPriority.CRITICAL,
            RevisionVector(1),
            NOW,
            shutdown_control=True,
        )
        assert not coordinator.submit(late_control).accepted
        close_gate.set()
        await stop_task
        assert handled == []
        assert coordinator.diagnostics().lanes[0].queue_depth == 0
        assert not coordinator.cancel("late-control", "must not be registered")

    asyncio.run(scenario())


def test_fail_fast_stop_is_owned_and_awaitable() -> None:
    async def scenario() -> None:
        closed: list[str] = []

        async def handler(_work: RuntimeWorkItem[object], _token: object) -> str:
            raise RuntimeError("provider-secret")

        async def close_resource() -> None:
            closed.append("closed")

        coordinator = RuntimeCoordinator(FakeRuntimeClock(NOW))
        coordinator.register_lane(
            RuntimeLanePolicy(
                "critical",
                1,
                QueuePolicy.REJECT_NEW,
                error_policy=LaneErrorPolicy.FAIL_FAST_CONTROLLED,
            ),
            handler,
        )
        coordinator.register_close_hook(close_resource)
        await coordinator.start()
        coordinator.submit(item("bad", "critical"))
        assert (await coordinator.next_outcome()).disposition is WorkDisposition.FAILED
        await coordinator.wait_stopped()
        assert coordinator.state.value == "stopped"
        assert closed == ["closed"]
        assert coordinator.diagnostics().owned_task_count == 0

    asyncio.run(scenario())
