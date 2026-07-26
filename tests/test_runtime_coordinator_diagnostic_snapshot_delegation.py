from __future__ import annotations

from queue import Queue

from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import ActivityPlannerThread
from app.runtime.event_queue import EventQueue
from app.runtime.runtime_coordinator import RuntimeCoordinator


class StubSnapshotBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"delegated": True}


class StubActionPlanner(ActionPlanner):
    pass


class StubActionScheduler(ActionScheduler):
    pass


def test_runtime_coordinator_delegates_diagnostic_snapshot(runtime_components) -> None:
    builder = StubSnapshotBuilder()
    coordinator = RuntimeCoordinator(
        runtime_components.event_queue,
        runtime_components.activity_manager,
        runtime_components.action_planner,
        runtime_components.action_scheduler,
        runtime_components.activity_planning_request_queue,
        runtime_components.activity_planner_thread,
        runtime_components.activity_executor_thread,
        runtime_diagnostic_snapshot_builder=builder,
    )

    result = coordinator.diagnostic_snapshot()

    assert result == {"delegated": True}
    assert len(builder.calls) == 1
    assert builder.calls[0]["activity_manager"] is runtime_components.activity_manager
    assert builder.calls[0]["plugin_manager"] is None
