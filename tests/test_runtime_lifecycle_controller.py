import pytest

from app.runtime.activity_manager import ActivityManager
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.runtime_lifecycle_controller import RuntimeLifecycleController
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


class FakeRuntimeLoop:
    def __init__(self) -> None:
        self.controller: RuntimeLifecycleController | None = None
        self.calls = 0

    async def run_once(self) -> None:
        self.calls += 1
        assert self.controller is not None
        self.controller.stop()


class FakeThread:
    def __init__(self, *, alive: bool = False) -> None:
        self.alive = alive
        self.started = False
        self.stopped = False
        self.join_timeouts: list[float | None] = []

    def is_alive(self) -> bool:
        return self.alive

    def start(self) -> None:
        self.started = True
        self.alive = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        self.alive = False


class FakePluginManager:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown_plugins(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_initializer_failure_does_not_prevent_runtime_start() -> None:
    calls: list[str] = []

    async def fail() -> None:
        calls.append("fail")
        raise RuntimeError("initializer failure")

    async def succeed() -> None:
        calls.append("succeed")

    runtime_loop = FakeRuntimeLoop()
    controller = RuntimeLifecycleController(
        runtime_loop=runtime_loop,  # type: ignore[arg-type]
        activity_planner_thread=FakeThread(),  # type: ignore[arg-type]
        activity_executor_thread=FakeThread(),  # type: ignore[arg-type]
        plugin_manager=None,
        ongoing_activity_coordinator=OngoingActivityCoordinator(ActivityManager()),
        async_initializers=(fail, succeed),
        autonomous_planning_enabled=False,
        trace_logger=TraceLogger(),
        idle_sleep_seconds=0.0,
    )
    runtime_loop.controller = controller

    await controller.run()

    assert calls == ["fail", "succeed"]
    assert runtime_loop.calls == 1


def test_stop_stops_and_joins_threads_then_shuts_down_plugin_and_ongoing() -> None:
    manager = ActivityManager()
    manager.start_ongoing_activity(
        activity_type="test",
        goal="継続中",
        expected_input="入力",
        end_condition="終了",
        context={},
    )
    planner_thread = FakeThread(alive=True)
    executor_thread = FakeThread(alive=True)
    plugin_manager = FakePluginManager()
    controller = RuntimeLifecycleController(
        runtime_loop=FakeRuntimeLoop(),  # type: ignore[arg-type]
        activity_planner_thread=planner_thread,  # type: ignore[arg-type]
        activity_executor_thread=executor_thread,  # type: ignore[arg-type]
        plugin_manager=plugin_manager,  # type: ignore[arg-type]
        ongoing_activity_coordinator=OngoingActivityCoordinator(manager),
        async_initializers=(),
        autonomous_planning_enabled=True,
        trace_logger=TraceLogger(),
        thread_join_timeout_seconds=0.25,
    )

    controller.stop()

    assert planner_thread.stopped is True
    assert executor_thread.stopped is True
    assert planner_thread.join_timeouts == [0.25]
    assert executor_thread.join_timeouts == [0.25]
    assert plugin_manager.shutdown_calls == 1
    assert manager.ongoing_activity is None
    assert manager.ongoing_activity_history[-1].status.value == "canceled"
