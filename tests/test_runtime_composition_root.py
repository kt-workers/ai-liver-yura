from unittest.mock import MagicMock

import pytest

from app.runtime.runtime_composition_root import RuntimeCompositionRoot

pytestmark = pytest.mark.unit


def test_build_execution_preserves_injected_components() -> None:
    event_executor = MagicMock()
    runtime_loop = MagicMock()
    host_controller = MagicMock()

    composition = RuntimeCompositionRoot().build_execution(
        event_queue=MagicMock(),
        activity_manager=MagicMock(),
        action_planner=MagicMock(),
        action_scheduler=MagicMock(),
        activity_planning_request_queue=MagicMock(),
        activity_planner_thread=MagicMock(),
        activity_executor_thread=MagicMock(),
        agent_life_service=MagicMock(),
        plugin_manager=MagicMock(),
        ongoing_activity_coordinator=MagicMock(),
        event_handler=MagicMock(),
        event_enrichers_provider=MagicMock(),
        autonomous_planning_enabled=True,
        require_startup_completion=False,
        autonomous_planning_poll_seconds=0.5,
        async_initializers=(),
        trace_logger=MagicMock(),
        event_executor=event_executor,
        runtime_loop=runtime_loop,
        host_controller=host_controller,
    )

    assert composition.event_executor is event_executor
    assert composition.runtime_loop is runtime_loop
    assert composition.host_controller is host_controller


def test_build_execution_connects_created_loop_to_host_controller() -> None:
    composition = RuntimeCompositionRoot().build_execution(
        event_queue=MagicMock(),
        activity_manager=MagicMock(),
        action_planner=MagicMock(),
        action_scheduler=MagicMock(),
        activity_planning_request_queue=MagicMock(),
        activity_planner_thread=MagicMock(),
        activity_executor_thread=MagicMock(),
        agent_life_service=MagicMock(),
        plugin_manager=None,
        ongoing_activity_coordinator=MagicMock(),
        event_handler=MagicMock(),
        event_enrichers_provider=MagicMock(return_value=()),
        autonomous_planning_enabled=False,
        require_startup_completion=False,
        autonomous_planning_poll_seconds=0.5,
        async_initializers=(),
        trace_logger=MagicMock(),
    )

    assert composition.host_controller._runtime_loop is composition.runtime_loop
    assert composition.runtime_loop.autonomous_planning_enabled is False
