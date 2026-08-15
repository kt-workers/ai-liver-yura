import asyncio
from datetime import datetime, timezone

from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    FakeRuntimeClock,
    QueuePolicy,
    RuntimeCoordinator,
    RuntimeLanePolicy,
    RuntimeWorkItem,
    WorkPriority,
)
from app.runtime.lifecycle import DependencyState, RetryPolicy, RuntimeLifecycle

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def test_reconnect_is_bounded_and_does_not_stop_other_dependencies() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock)
        reconnected: list[str] = []

        async def reconnect() -> None:
            reconnected.append("provider")

        async def close() -> None:
            return None

        lifecycle.register_dependency(
            "provider", RetryPolicy(2, 1, 4), reconnect=reconnect, close=close
        )
        lifecycle.register_dependency(
            "body", RetryPolicy(2, 1, 4), reconnect=reconnect, close=close
        )
        snapshot = lifecycle.report_failure("provider", ConnectionError())
        assert snapshot.state is DependencyState.DEGRADED
        assert lifecycle.schedule_reconnect("provider")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert reconnected == ["provider"]
        assert lifecycle.snapshot("provider").state is DependencyState.AVAILABLE
        assert lifecycle.snapshot("body").state is DependencyState.AVAILABLE
        assert clock.sleeps == [1]

    asyncio.run(scenario())


def test_shutdown_cancels_retry_and_closes_all_dependencies() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock)
        closed: list[str] = []
        gate = asyncio.Event()

        async def reconnect() -> None:
            await gate.wait()

        async def close() -> None:
            closed.append("closed")

        lifecycle.register_dependency(
            "provider", RetryPolicy(2, 1, 4), reconnect=reconnect, close=close
        )
        lifecycle.report_failure("provider", ConnectionError())
        assert lifecycle.schedule_reconnect("provider")
        await lifecycle.stop()
        assert closed == ["closed"]
        assert lifecycle.snapshot("provider").state is DependencyState.CLOSED
        assert not lifecycle.schedule_reconnect("provider")
        await lifecycle.stop()
        assert closed == ["closed"]

    asyncio.run(scenario())


def test_failure_diagnostics_are_rate_limited_and_retry_stops_at_bound() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock)
        attempts = 0

        async def reconnect() -> None:
            nonlocal attempts
            attempts += 1
            raise ConnectionError()

        async def close() -> None:
            return None

        lifecycle.register_dependency(
            "provider", RetryPolicy(3, 1, 4), reconnect=reconnect, close=close
        )
        lifecycle.report_failure("provider", ConnectionError())
        assert lifecycle.allow_diagnostic("provider", 10)
        assert not lifecycle.allow_diagnostic("provider", 10)
        clock.advance(10)
        assert lifecycle.allow_diagnostic("provider", 10)
        assert lifecycle.schedule_reconnect("provider")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert attempts == 2
        assert lifecycle.snapshot("provider").state is DependencyState.UNAVAILABLE

    asyncio.run(scenario())


def test_coordinator_shutdown_closes_lifecycle_dependencies() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock)
        closed: list[str] = []

        async def reconnect() -> None:
            return None

        async def close() -> None:
            closed.append("provider")

        lifecycle.register_dependency(
            "provider", RetryPolicy(2, 1, 4), reconnect=reconnect, close=close
        )
        coordinator = RuntimeCoordinator(clock)
        coordinator.register_lane(
            RuntimeLanePolicy("lane", 1, QueuePolicy.REJECT_NEW),
            lambda _work, _token: asyncio.sleep(0),
        )
        coordinator.register_close_hook(lifecycle.close)
        await coordinator.start()
        coordinator.submit(
            RuntimeWorkItem(
                "work",
                "lane",
                None,
                WorkPriority.NORMAL,
                RevisionVector(1),
                NOW,
            )
        )
        await coordinator.next_outcome()
        await coordinator.stop()
        assert closed == ["provider"]
        assert lifecycle.snapshot("provider").state is DependencyState.CLOSED

    asyncio.run(scenario())
