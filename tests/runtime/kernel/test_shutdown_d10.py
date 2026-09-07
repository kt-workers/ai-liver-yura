import asyncio
from datetime import datetime, timezone
from typing import cast

import pytest

from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    FakeRuntimeClock,
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeCoordinator,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkPriority,
)
from app.runtime.shutdown import (
    RuntimeShutdownError,
    RuntimeShutdownPolicy,
    RuntimeShutdownStage,
)

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
SCHEDULER_POLICY = RuntimeSchedulerPolicy("test.scheduler", 1, 8)


def shutdown_policy(
    *,
    in_flight: float = 1.0,
    persistence: float = 1.0,
    resource: float = 1.0,
    owned_join: float = 1.0,
) -> RuntimeShutdownPolicy:
    return RuntimeShutdownPolicy(
        "test.shutdown",
        1,
        in_flight,
        persistence,
        resource,
        owned_join,
    )


def coordinator(policy: RuntimeShutdownPolicy | None = None) -> RuntimeCoordinator:
    return RuntimeCoordinator(
        FakeRuntimeClock(NOW),
        SCHEDULER_POLICY,
        policy or shutdown_policy(),
    )


def lane_policy() -> RuntimeLanePolicy:
    return RuntimeLanePolicy(
        "lane",
        2,
        QueuePolicy.REJECT_NEW,
        1,
        0.0,
        LaneErrorPolicy.ISOLATE,
    )


def test_shutdown_policy_rejects_bool_nan_infinity_and_negative() -> None:
    with pytest.raises(ValueError):
        RuntimeShutdownPolicy("shutdown", 1, cast(float, True), 1.0, 1.0, 1.0)
    for invalid in (float("nan"), float("inf"), float("-inf"), -1.0):
        with pytest.raises(ValueError):
            RuntimeShutdownPolicy("shutdown", 1, 1.0, invalid, 1.0, 1.0)


def test_missing_shutdown_policy_has_no_hidden_default() -> None:
    with pytest.raises(ValueError):
        RuntimeCoordinator(
            FakeRuntimeClock(NOW),
            SCHEDULER_POLICY,
            cast(RuntimeShutdownPolicy, None),
        )


def test_producer_stop_precedes_final_persistence_and_resource_close() -> None:
    async def scenario() -> None:
        order: list[str] = []
        runtime = coordinator()

        async def producer_stop() -> None:
            order.append("producer")

        async def persist() -> None:
            order.append("persistence")

        async def close() -> None:
            order.append("close")

        runtime.register_producer_stop_hook(producer_stop)
        runtime.register_final_persistence_hook(persist)
        runtime.register_close_hook(close)
        await runtime.start()
        await runtime.stop()

        assert order == ["producer", "persistence", "close"]
        assert runtime.state.value == "stopped"

    asyncio.run(scenario())


def test_producer_stop_failure_does_not_skip_persistence_or_close() -> None:
    async def scenario() -> None:
        order: list[str] = []
        runtime = coordinator()

        async def producer_stop() -> None:
            order.append("producer")
            raise RuntimeError("producer停止失敗")

        async def persist() -> None:
            order.append("persistence")

        async def close() -> None:
            order.append("close")

        runtime.register_producer_stop_hook(producer_stop)
        runtime.register_final_persistence_hook(persist)
        runtime.register_close_hook(close)
        await runtime.start()
        await runtime.stop()

        assert order == ["producer", "persistence", "close"]
        assert any(
            failure.stage is RuntimeShutdownStage.PRODUCER_STOP
            for failure in runtime.shutdown_failures
        )

    asyncio.run(scenario())


def test_final_persistence_timeout_still_closes_resources() -> None:
    async def scenario() -> None:
        order: list[str] = []
        never = asyncio.Event()
        runtime = coordinator(shutdown_policy(persistence=0.01))

        async def persist() -> None:
            order.append("persistence")
            await never.wait()

        async def close() -> None:
            order.append("close")

        runtime.register_final_persistence_hook(persist)
        runtime.register_close_hook(close)
        await runtime.start()
        await runtime.stop()

        assert order == ["persistence", "close"]
        assert any(
            failure.stage is RuntimeShutdownStage.FINAL_PERSISTENCE
            and failure.error_class == "TimeoutError"
            for failure in runtime.shutdown_failures
        )

    asyncio.run(scenario())


def test_resource_close_timeout_does_not_skip_earlier_registered_resource() -> None:
    async def scenario() -> None:
        order: list[str] = []
        never = asyncio.Event()
        runtime = coordinator(shutdown_policy(resource=0.01))

        async def first_close() -> None:
            order.append("first")

        async def second_close() -> None:
            order.append("second")
            await never.wait()

        runtime.register_close_hook(first_close)
        runtime.register_close_hook(second_close)
        await runtime.start()
        await runtime.stop()

        assert order == ["second", "first"]
        assert any(
            failure.stage is RuntimeShutdownStage.RESOURCE_CLOSE
            and failure.error_class == "TimeoutError"
            for failure in runtime.shutdown_failures
        )

    asyncio.run(scenario())


def test_late_non_interruptible_result_is_not_committed_as_completed() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        runtime = coordinator(shutdown_policy(in_flight=0.01, owned_join=0.01))

        async def handler(_work: RuntimeWorkItem[object], _token: object) -> str:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return "late"

        runtime.register_lane(lane_policy(), handler)
        await runtime.start()
        runtime.submit(
            RuntimeWorkItem(
                "late",
                "lane",
                None,
                WorkPriority.NORMAL,
                RevisionVector(1),
                NOW,
                interruptible=False,
            )
        )
        await started.wait()

        with pytest.raises(RuntimeShutdownError):
            await runtime.stop()
        assert runtime.state.value == "stopping"

        release.set()
        outcome = await runtime.next_outcome()
        assert outcome.disposition.value == "cancelled"

    asyncio.run(scenario())


def test_owned_task_join_timeout_never_reports_stopped_success() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        runtime = coordinator(shutdown_policy(in_flight=0.0, owned_join=0.0))

        async def handler(_work: RuntimeWorkItem[object], _token: object) -> None:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        runtime.register_lane(lane_policy(), handler)
        await runtime.start()
        runtime.submit(
            RuntimeWorkItem(
                "pending",
                "lane",
                None,
                WorkPriority.NORMAL,
                RevisionVector(1),
                NOW,
                interruptible=False,
            )
        )
        await started.wait()

        with pytest.raises(RuntimeShutdownError) as captured:
            await runtime.stop()
        assert runtime.state.value == "stopping"
        assert any(
            failure.stage is RuntimeShutdownStage.OWNED_TASK_JOIN
            for failure in captured.value.failures
        )
        release.set()
        await runtime.next_outcome()

    asyncio.run(scenario())


def test_terminal_failure_double_stop_does_not_rerun_shutdown_hooks() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[str] = []
        runtime = coordinator(shutdown_policy(in_flight=0.0, owned_join=0.0))

        async def handler(_work: RuntimeWorkItem[object], _token: object) -> None:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        async def producer() -> None:
            calls.append("producer")

        async def persistence() -> None:
            calls.append("persistence")

        async def close() -> None:
            calls.append("close")

        runtime.register_lane(lane_policy(), handler)
        runtime.register_producer_stop_hook(producer)
        runtime.register_final_persistence_hook(persistence)
        runtime.register_close_hook(close)
        await runtime.start()
        runtime.submit(
            RuntimeWorkItem(
                "pending",
                "lane",
                None,
                WorkPriority.NORMAL,
                RevisionVector(1),
                NOW,
                interruptible=False,
            )
        )
        await started.wait()

        with pytest.raises(RuntimeShutdownError):
            await runtime.stop()
        assert calls == ["producer", "persistence", "close"]
        with pytest.raises(RuntimeShutdownError):
            await runtime.stop()
        assert calls == ["producer", "persistence", "close"]

        release.set()
        await runtime.next_outcome()

    asyncio.run(scenario())


def test_successful_double_stop_is_idempotent() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        runtime = coordinator()

        async def close() -> None:
            calls.append("close")

        runtime.register_close_hook(close)
        await runtime.start()
        await runtime.stop()
        await runtime.stop()
        assert calls == ["close"]
        assert runtime.state.value == "stopped"

    asyncio.run(scenario())
