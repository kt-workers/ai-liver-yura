import asyncio
from datetime import datetime, timezone
from typing import cast

import pytest

from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    FakeRuntimeClock,
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkPriority,
)
from app.runtime.kernel import (
    RuntimeCoordinator as KernelRuntimeCoordinator,
)
from app.runtime.kernel import (
    RuntimeLanePolicy as KernelRuntimeLanePolicy,
)
from app.runtime.lifecycle import (
    DependencyFailure,
    DependencyRetryPolicy,
    DependencyState,
    RuntimeLifecycle,
)
from app.runtime.shutdown import RuntimeShutdownError, RuntimeShutdownPolicy

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
TEST_SCHEDULER_POLICY = RuntimeSchedulerPolicy("test.scheduler", 1, 8)


def shutdown_policy(
    *,
    resource_close_grace_seconds: float = 1.0,
) -> RuntimeShutdownPolicy:
    return RuntimeShutdownPolicy(
        "test.shutdown",
        1,
        1.0,
        1.0,
        resource_close_grace_seconds,
        1.0,
    )


def retry_policy(
    dependency_id: str,
    *,
    revision: int = 1,
    retry_enabled: bool = True,
    max_retry_attempts: int = 3,
    initial_backoff_seconds: float = 1.0,
    backoff_multiplier: float = 2.0,
    max_backoff_seconds: float = 4.0,
    diagnostic_min_interval_seconds: float = 10.0,
) -> DependencyRetryPolicy:
    return DependencyRetryPolicy(
        "test.retry",
        revision,
        dependency_id,
        retry_enabled,
        max_retry_attempts,
        initial_backoff_seconds,
        backoff_multiplier,
        max_backoff_seconds,
        diagnostic_min_interval_seconds,
    )


def RuntimeCoordinator(clock: FakeRuntimeClock) -> KernelRuntimeCoordinator:
    return KernelRuntimeCoordinator(clock, TEST_SCHEDULER_POLICY, shutdown_policy())


def RuntimeLanePolicy(
    lane_id: str,
    queue_capacity: int,
    queue_policy: QueuePolicy,
) -> KernelRuntimeLanePolicy:
    return KernelRuntimeLanePolicy(
        lane_id,
        queue_capacity,
        queue_policy,
        1,
        1.0,
        LaneErrorPolicy.ISOLATE,
    )


def test_retry_policy_rejects_invalid_numeric_values() -> None:
    with pytest.raises(ValueError):
        DependencyRetryPolicy(
            "retry",
            1,
            "provider",
            True,
            cast(int, True),
            1.0,
            2.0,
            4.0,
            0.0,
        )
    for invalid in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
        with pytest.raises(ValueError):
            DependencyRetryPolicy(
                "retry",
                1,
                "provider",
                True,
                1,
                invalid,
                2.0,
                4.0,
                0.0,
            )
    with pytest.raises(ValueError):
        DependencyRetryPolicy(
            "retry",
            1,
            "provider",
            True,
            1,
            1.0,
            cast(float, True),
            4.0,
            0.0,
        )


def test_retry_delay_uses_initial_multiplier_and_cap_without_jitter() -> None:
    policy = retry_policy(
        "provider",
        max_retry_attempts=4,
        initial_backoff_seconds=1.0,
        backoff_multiplier=3.0,
        max_backoff_seconds=5.0,
    )
    assert [policy.delay_for(number) for number in range(1, 5)] == [1.0, 3.0, 5.0, 5.0]
    assert [policy.delay_for(number) for number in range(1, 5)] == [1.0, 3.0, 5.0, 5.0]


def test_max_retry_attempts_zero_and_non_retryable_failure_do_not_retry() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock, shutdown_policy())

        async def reconnect() -> DependencyFailure | None:
            raise AssertionError("retryしてはいけません")

        async def close() -> None:
            return None

        lifecycle.register_dependency(
            retry_policy("none", max_retry_attempts=0),
            reconnect=reconnect,
            close=close,
        )
        snapshot = lifecycle.report_failure("none", DependencyFailure("temporary", True))
        assert snapshot.state is DependencyState.UNAVAILABLE
        assert not lifecycle.schedule_reconnect("none")

        lifecycle.register_dependency(
            retry_policy("permanent"),
            reconnect=reconnect,
            close=close,
        )
        snapshot = lifecycle.report_failure(
            "permanent", DependencyFailure("credential_rejected", False)
        )
        assert snapshot.state is DependencyState.UNAVAILABLE
        assert not lifecycle.schedule_reconnect("permanent")
        assert clock.sleeps == []
        await lifecycle.stop()

    asyncio.run(scenario())


def test_reconnect_is_bounded_and_does_not_stop_other_dependencies() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock, shutdown_policy())
        attempts = 0

        async def reconnect_provider() -> DependencyFailure | None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return DependencyFailure("temporary", True)
            return None

        async def reconnect_body() -> DependencyFailure | None:
            return None

        async def close() -> None:
            return None

        lifecycle.register_dependency(
            retry_policy("provider"),
            reconnect=reconnect_provider,
            close=close,
        )
        lifecycle.register_dependency(
            retry_policy("body"),
            reconnect=reconnect_body,
            close=close,
        )
        snapshot = lifecycle.report_failure(
            "provider", DependencyFailure("temporary", True)
        )
        assert snapshot.state is DependencyState.DEGRADED
        assert lifecycle.schedule_reconnect("provider")
        for _ in range(12):
            await asyncio.sleep(0)
            if lifecycle.snapshot("provider").state is DependencyState.AVAILABLE:
                break
        assert attempts == 3
        assert lifecycle.snapshot("provider").state is DependencyState.AVAILABLE
        assert lifecycle.snapshot("body").state is DependencyState.AVAILABLE
        assert clock.sleeps == [1.0, 2.0, 4.0]
        await lifecycle.stop()

    asyncio.run(scenario())


def test_failure_diagnostics_use_strict_interval_boundary() -> None:
    clock = FakeRuntimeClock(NOW)
    lifecycle = RuntimeLifecycle(clock, shutdown_policy())

    async def reconnect() -> DependencyFailure | None:
        return None

    async def close() -> None:
        return None

    lifecycle.register_dependency(
        retry_policy("provider", diagnostic_min_interval_seconds=10.0),
        reconnect=reconnect,
        close=close,
    )
    assert lifecycle.allow_diagnostic("provider", "temporary")
    clock.advance(9.999)
    assert not lifecycle.allow_diagnostic("provider", "temporary")
    assert lifecycle.suppressed_diagnostic_count("provider", "temporary") == 1
    clock.advance(0.001)
    assert lifecycle.allow_diagnostic("provider", "temporary")


def test_same_generation_mutation_rejected_and_equal_update_is_idempotent() -> None:
    clock = FakeRuntimeClock(NOW)
    lifecycle = RuntimeLifecycle(clock, shutdown_policy())

    async def reconnect() -> DependencyFailure | None:
        return None

    async def close() -> None:
        return None

    original = retry_policy("provider")
    lifecycle.register_dependency(original, reconnect=reconnect, close=close)
    snapshot = lifecycle.update_retry_policy("provider", original)
    assert snapshot.retry_policy_revision == 1
    with pytest.raises(ValueError, match="同一retry policy generation"):
        lifecycle.update_retry_policy(
            "provider",
            retry_policy("provider", diagnostic_min_interval_seconds=11.0),
        )


def test_policy_revision_supersedes_old_retry_without_old_result_commit() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock, shutdown_policy())
        started = asyncio.Event()
        release = asyncio.Event()

        async def reconnect() -> DependencyFailure | None:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return None

        async def close() -> None:
            return None

        lifecycle.register_dependency(
            retry_policy("provider", revision=1),
            reconnect=reconnect,
            close=close,
        )
        lifecycle.report_failure("provider", DependencyFailure("temporary", True))
        assert lifecycle.schedule_reconnect("provider")
        await started.wait()
        lifecycle.update_retry_policy("provider", retry_policy("provider", revision=2))

        stop_task = asyncio.create_task(lifecycle.stop())
        await asyncio.sleep(0)
        assert not stop_task.done()
        release.set()
        await stop_task
        snapshot = lifecycle.snapshot("provider")
        assert snapshot.retry_policy_revision == 2
        assert snapshot.state is DependencyState.CLOSED
        assert not lifecycle.schedule_reconnect("provider")

    asyncio.run(scenario())


def test_untyped_reconnect_exception_is_fixed_non_retryable_failure() -> None:
    async def scenario() -> None:
        lifecycle = RuntimeLifecycle(FakeRuntimeClock(NOW), shutdown_policy())

        async def reconnect() -> DependencyFailure | None:
            raise RuntimeError("provider固有の秘密本文")

        async def close() -> None:
            return None

        lifecycle.register_dependency(
            retry_policy("provider"),
            reconnect=reconnect,
            close=close,
        )
        lifecycle.report_failure("provider", DependencyFailure("temporary", True))
        assert lifecycle.schedule_reconnect("provider")
        for _ in range(4):
            await asyncio.sleep(0)
        snapshot = lifecycle.snapshot("provider")
        assert snapshot.state is DependencyState.UNAVAILABLE
        assert snapshot.last_failure_code == "unclassified_reconnect_failure"
        await lifecycle.stop()

    asyncio.run(scenario())


def test_shutdown_cancels_retry_and_closes_dependencies_in_reverse_order() -> None:
    async def scenario() -> None:
        lifecycle = RuntimeLifecycle(FakeRuntimeClock(NOW), shutdown_policy())
        closed: list[str] = []
        retry_gate = asyncio.Event()

        async def reconnect() -> DependencyFailure | None:
            await retry_gate.wait()
            return None

        def close_for(name: str):  # type: ignore[no-untyped-def]
            async def close() -> None:
                closed.append(name)

            return close

        lifecycle.register_dependency(
            retry_policy("first"), reconnect=reconnect, close=close_for("first")
        )
        lifecycle.register_dependency(
            retry_policy("second"), reconnect=reconnect, close=close_for("second")
        )
        lifecycle.report_failure("first", DependencyFailure("temporary", True))
        assert lifecycle.schedule_reconnect("first")
        await lifecycle.stop()
        assert closed == ["second", "first"]
        assert lifecycle.snapshot("first").state is DependencyState.CLOSED
        assert lifecycle.snapshot("second").state is DependencyState.CLOSED
        assert not lifecycle.schedule_reconnect("first")
        await lifecycle.stop()
        assert closed == ["second", "first"]

    asyncio.run(scenario())


def test_dependency_close_failure_does_not_skip_later_close() -> None:
    async def scenario() -> None:
        lifecycle = RuntimeLifecycle(FakeRuntimeClock(NOW), shutdown_policy())
        closed: list[str] = []

        async def reconnect() -> DependencyFailure | None:
            return None

        async def first_close() -> None:
            closed.append("first")

        async def second_close() -> None:
            closed.append("second")
            raise RuntimeError("close失敗")

        lifecycle.register_dependency(
            retry_policy("first"), reconnect=reconnect, close=first_close
        )
        lifecycle.register_dependency(
            retry_policy("second"), reconnect=reconnect, close=second_close
        )
        snapshots = await lifecycle.stop()
        assert closed == ["second", "first"]
        assert all(snapshot.state is DependencyState.CLOSED for snapshot in snapshots)
        assert lifecycle.shutdown_failures
        with pytest.raises(RuntimeShutdownError):
            await lifecycle.close()
        assert closed == ["second", "first"]

    asyncio.run(scenario())


def test_coordinator_shutdown_closes_lifecycle_dependencies() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        lifecycle = RuntimeLifecycle(clock, shutdown_policy())
        closed: list[str] = []

        async def reconnect() -> DependencyFailure | None:
            return None

        async def close() -> None:
            closed.append("provider")

        lifecycle.register_dependency(
            retry_policy("provider"), reconnect=reconnect, close=close
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


def test_missing_shutdown_policy_has_no_hidden_default() -> None:
    with pytest.raises(ValueError):
        RuntimeLifecycle(FakeRuntimeClock(NOW), cast(RuntimeShutdownPolicy, None))
