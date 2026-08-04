from __future__ import annotations

import pytest

from app.runtime.activity_manager import ActivityManager
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.runtime_host_controller import RuntimeHostController
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


class FakeRuntimeLoop:
    autonomous_planning_enabled = True


class FakeThread:
    def __init__(self) -> None:
        self.alive = True
        self.stopped = False
        self.join_timeouts: list[float | None] = []

    def is_alive(self) -> bool:
        return self.alive

    def start(self) -> None:
        self.alive = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        self.alive = False


class FakePluginManager:
    def __init__(self, planner: FakeThread, executor: FakeThread) -> None:
        self._planner = planner
        self._executor = executor
        self.shutdown_calls = 0

    def shutdown_plugins(self) -> None:
        assert self._planner.is_alive() is False
        assert self._executor.is_alive() is False
        self.shutdown_calls += 1


def test_default_shutdown_waits_long_enough_before_plugin_shutdown() -> None:
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

    assert planner.stopped is True
    assert executor.stopped is True
    assert planner.join_timeouts
    assert executor.join_timeouts
    assert planner.join_timeouts[0] is not None
    assert executor.join_timeouts[0] is not None
    assert 29.0 <= float(planner.join_timeouts[0]) <= 30.0
    assert 29.0 <= float(executor.join_timeouts[0]) <= 30.0
    assert plugin_manager.shutdown_calls == 1
