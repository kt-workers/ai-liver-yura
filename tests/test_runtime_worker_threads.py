from __future__ import annotations

import pytest

from app.runtime.activity_manager import ActivityManager
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.runtime_host_controller import RuntimeHostController
from app.runtime.runtime_worker_threads import (
    RuntimeThreadShutdownPolicy,
    RuntimeWorkerThreads,
)
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


class FakeThread:
    def __init__(self, *, alive: bool = True, stops_on_join: bool = True) -> None:
        self.alive = alive
        self.stops_on_join = stops_on_join
        self.start_calls = 0
        self.stop_calls = 0
        self.join_timeouts: list[float | None] = []

    def is_alive(self) -> bool:
        return self.alive

    def start(self) -> None:
        self.start_calls += 1
        self.alive = True

    def stop(self) -> None:
        self.stop_calls += 1

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        if self.stops_on_join:
            self.alive = False


class FakeRuntimeLoop:
    autonomous_planning_enabled = True


class FakePluginManager:
    def __init__(self, planner: FakeThread, executor: FakeThread) -> None:
        self._planner = planner
        self._executor = executor
        self.shutdown_calls = 0

    def shutdown_plugins(self) -> None:
        assert self._planner.is_alive() is False
        assert self._executor.is_alive() is False
        self.shutdown_calls += 1


def test_runtime_worker_threads_uses_shared_shutdown_policy() -> None:
    planner = FakeThread()
    executor = FakeThread()
    workers = RuntimeWorkerThreads(
        planner_thread=planner,
        executor_thread=executor,
        trace_logger=TraceLogger(),
        shutdown_policy=RuntimeThreadShutdownPolicy(join_timeout_seconds=30.0),
    )

    status = workers.stop(enabled=True)

    assert planner.stop_calls == 1
    assert executor.stop_calls == 1
    assert planner.join_timeouts == [30.0]
    assert executor.join_timeouts == [30.0]
    assert status.timed_out is False


def test_runtime_worker_threads_reports_shutdown_timeout() -> None:
    planner = FakeThread(stops_on_join=False)
    executor = FakeThread(stops_on_join=False)
    workers = RuntimeWorkerThreads(
        planner_thread=planner,
        executor_thread=executor,
        trace_logger=TraceLogger(),
        shutdown_policy=RuntimeThreadShutdownPolicy(join_timeout_seconds=0.1),
    )

    status = workers.stop(enabled=True)

    assert status.timed_out is True
    assert status.planner_alive is True
    assert status.executor_alive is True
    assert status.timeout_seconds == 0.1


def test_runtime_worker_threads_does_not_start_when_planning_disabled() -> None:
    planner = FakeThread(alive=False)
    executor = FakeThread(alive=False)
    workers = RuntimeWorkerThreads(
        planner_thread=planner,
        executor_thread=executor,
        trace_logger=TraceLogger(),
    )

    workers.start(enabled=False)

    assert planner.start_calls == 0
    assert executor.start_calls == 0


def test_runtime_host_stops_workers_before_plugin_shutdown() -> None:
    planner = FakeThread()
    executor = FakeThread()
    plugin_manager = FakePluginManager(planner, executor)
    controller = RuntimeHostController(
        runtime_loop=FakeRuntimeLoop(),  # type: ignore[arg-type]
        activity_planner_thread=planner,  # type: ignore[arg-type]
        activity_executor_thread=executor,  # type: ignore[arg-type]
        plugin_manager=plugin_manager,  # type: ignore[arg-type]
        ongoing_activity_coordinator=OngoingActivityCoordinator(ActivityManager()),
        async_initializers=(),
        trace_logger=TraceLogger(),
    )

    controller.stop()

    assert planner.join_timeouts == [30.0]
    assert executor.join_timeouts == [30.0]
    assert plugin_manager.shutdown_calls == 1


@pytest.mark.parametrize("timeout", [True, 0.0, float("inf"), 301.0])
def test_runtime_thread_shutdown_policy_rejects_invalid_timeout(
    timeout: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        RuntimeThreadShutdownPolicy(join_timeout_seconds=timeout)  # type: ignore[arg-type]
