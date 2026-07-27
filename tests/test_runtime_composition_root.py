from queue import Queue
from unittest.mock import MagicMock

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.buffered_event_dispatcher import BufferedEventDispatcher
from app.runtime.conversation_input_recorder import ConversationInputRecorder
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_dispatch_processor import EventDispatchProcessor
from app.runtime.event_filter import DefaultEventFilter
from app.runtime.event_ingress_processor import EventIngressProcessor
from app.runtime.event_prioritizer import DefaultEventPrioritizer
from app.runtime.event_subscriber_registry import EventSubscriberRegistry
from app.runtime.event_type_router import EventTypeRouter
from app.runtime.runtime_composition_root import RuntimeCompositionRoot
from app.runtime.runtime_coordinator import RuntimeCoordinator
from app.runtime.runtime_event_executor import RuntimeEventExecutor
from app.runtime.runtime_host_controller import RuntimeHostController
from app.runtime.runtime_loop import RuntimeLoop
from app.runtime.user_input_event_logger import UserInputEventLogger
from app.runtime.user_input_event_router import UserInputEventRouter
from app.runtime.user_input_interruption_coordinator import (
    UserInputInterruptionCoordinator,
)

pytestmark = pytest.mark.unit


def _build_coordinator(**overrides: object) -> RuntimeCoordinator:
    dependencies = {
        "event_queue": MagicMock(),
        "activity_manager": MagicMock(),
        "action_planner": MagicMock(),
        "action_scheduler": MagicMock(),
        "activity_planning_request_queue": Queue(),
        "activity_planner_thread": MagicMock(),
        "activity_executor_thread": MagicMock(),
        "agent_life_service": MagicMock(),
    }
    dependencies.update(overrides)
    return RuntimeCoordinator(**dependencies)  # type: ignore[arg-type]


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
        interaction_reaction_policy=None,
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
        interaction_reaction_policy=None,
    )

    assert isinstance(composition.event_executor, RuntimeEventExecutor)
    assert isinstance(composition.runtime_loop, RuntimeLoop)
    assert isinstance(composition.host_controller, RuntimeHostController)
    assert composition.host_controller._runtime_loop is composition.runtime_loop
    assert composition.runtime_loop.autonomous_planning_enabled is False


def test_build_execution_passes_interaction_reaction_policy_to_created_executor() -> None:
    interaction_reaction_policy = MagicMock()

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
        autonomous_planning_enabled=True,
        require_startup_completion=False,
        autonomous_planning_poll_seconds=0.5,
        async_initializers=(),
        trace_logger=MagicMock(),
        interaction_reaction_policy=interaction_reaction_policy,
    )

    assert (
        composition.event_executor._interaction_reaction_policy
        is interaction_reaction_policy
    )


def test_runtime_coordinator_preserves_injected_execution_components() -> None:
    event_executor = MagicMock()
    runtime_loop = MagicMock(autonomous_planning_enabled=False)
    host_controller = MagicMock()

    coordinator = _build_coordinator(
        runtime_event_executor=event_executor,
        runtime_loop=runtime_loop,
        runtime_host_controller=host_controller,
    )

    assert coordinator._runtime_event_executor is event_executor
    assert coordinator._runtime_loop is runtime_loop
    assert coordinator._runtime_host_controller is host_controller
    assert coordinator.autonomous_planning_enabled is False


def test_runtime_coordinator_builds_execution_components_and_keeps_enricher_live() -> None:
    coordinator = _build_coordinator(autonomous_planning_enabled=False)
    enricher = MagicMock(
        side_effect=lambda event: AgentEvent(
            event_type=event.event_type,
            payload={**event.payload, "enriched": True},
        )
    )

    coordinator.register_event_enricher(enricher)
    providers = coordinator._runtime_event_executor._event_enrichers_provider()

    assert isinstance(coordinator._runtime_event_executor, RuntimeEventExecutor)
    assert isinstance(coordinator._runtime_loop, RuntimeLoop)
    assert isinstance(coordinator._runtime_host_controller, RuntimeHostController)
    assert providers == (enricher,)
    assert coordinator._runtime_host_controller._runtime_loop is coordinator._runtime_loop
    assert coordinator._runtime_loop._event_handler == coordinator._handle_event
    assert providers[0](
        AgentEvent(event_type=AgentEventType.USER_TEXT, payload={})
    ).payload == {"enriched": True}


def test_runtime_coordinator_builds_event_pipeline_components() -> None:
    coordinator = _build_coordinator()

    assert isinstance(coordinator._event_filter, DefaultEventFilter)
    assert isinstance(coordinator._event_prioritizer, DefaultEventPrioritizer)
    assert isinstance(coordinator._event_buffer, EventBuffer)
    assert isinstance(
        coordinator._event_subscriber_registry,
        EventSubscriberRegistry,
    )
    assert isinstance(coordinator._user_input_event_logger, UserInputEventLogger)
    assert isinstance(coordinator._user_input_event_router, UserInputEventRouter)
    assert isinstance(
        coordinator._buffered_event_dispatcher,
        BufferedEventDispatcher,
    )
    assert isinstance(
        coordinator._user_input_interruption_coordinator,
        UserInputInterruptionCoordinator,
    )
    assert isinstance(coordinator._event_type_router, EventTypeRouter)
    assert isinstance(coordinator._event_dispatch_processor, EventDispatchProcessor)
    assert isinstance(
        coordinator._conversation_input_recorder,
        ConversationInputRecorder,
    )
    assert isinstance(coordinator._event_ingress_processor, EventIngressProcessor)


def test_runtime_coordinator_preserves_injected_event_pipeline_components() -> None:
    injected = {
        "event_filter": MagicMock(),
        "event_prioritizer": MagicMock(),
        "event_buffer": MagicMock(),
        "conversation_logger": MagicMock(),
        "conversation_input_recorder": MagicMock(),
        "event_subscriber_registry": MagicMock(),
        "event_ingress_processor": MagicMock(),
        "event_dispatch_processor": MagicMock(),
        "event_type_router": MagicMock(),
        "user_input_interruption_coordinator": MagicMock(),
        "buffered_event_dispatcher": MagicMock(),
        "user_input_event_logger": MagicMock(),
        "user_input_event_router": MagicMock(),
    }

    coordinator = _build_coordinator(**injected)

    for name, component in injected.items():
        assert getattr(coordinator, f"_{name}") is component
