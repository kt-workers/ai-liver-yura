import asyncio
from datetime import datetime, timedelta, timezone

from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    FakeRuntimeClock,
    QueuePolicy,
    RuntimeCoordinator,
    RuntimeHealth,
    RuntimeLanePolicy,
    RuntimeWorkItem,
    WorkDisposition,
    WorkPriority,
)

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


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
        outcomes = {outcome.work_id: outcome for outcome in [
            await coordinator.next_outcome(),
            await coordinator.next_outcome(),
            await coordinator.next_outcome(),
            await coordinator.next_outcome(),
        ]}
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
                "combined",
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
        assert admission.admitted_work_id == "combined"
        await asyncio.sleep(0)
        gate.set()
        assert (await coordinator.next_outcome()).work_id == "combined"
        await coordinator.stop()

    asyncio.run(scenario())
