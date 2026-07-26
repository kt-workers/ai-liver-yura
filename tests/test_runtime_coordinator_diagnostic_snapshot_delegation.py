from __future__ import annotations

from queue import Queue
from unittest.mock import Mock

from app.runtime.activity_manager import ActivityManager
from app.runtime.event_queue import EventQueue
from app.runtime.runtime_coordinator import RuntimeCoordinator


class StubSnapshotBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"delegated": True}


def test_runtime_coordinator_delegates_diagnostic_snapshot() -> None:
    builder = StubSnapshotBuilder()
    activity_manager = ActivityManager()
    coordinator = RuntimeCoordinator(
        event_queue=EventQueue(),
        activity_manager=activity_manager,
        action_planner=Mock(),
        action_scheduler=Mock(),
        activity_planning_request_queue=Queue(),
        activity_planner_thread=Mock(),
        activity_executor_thread=Mock(),
        runtime_diagnostic_snapshot_builder=builder,
    )

    result = coordinator.diagnostic_snapshot()

    assert result == {"delegated": True}
    assert len(builder.calls) == 1
    assert builder.calls[0]["state"] is coordinator.agent_state
    assert builder.calls[0]["activity_manager"] is activity_manager
    assert builder.calls[0]["plugin_manager"] is None
