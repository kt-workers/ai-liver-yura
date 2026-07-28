from unittest.mock import AsyncMock, MagicMock

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
from app.runtime.user_input_event_logger import UserInputEventLogger
from app.runtime.user_input_event_router import UserInputEventRouter
from app.runtime.user_input_interruption_coordinator import (
    UserInputInterruptionCoordinator,
)
from app.utils.conversation_log import ConversationLogger

pytestmark = pytest.mark.unit


def _build_event_pipeline(**overrides: object):
    dependencies = {
        "event_queue": MagicMock(),
        "activity_manager": MagicMock(),
        "action_scheduler": MagicMock(),
        "activity_planner_thread": MagicMock(),
        "activity_executor_thread": MagicMock(),
        "agent_life_service": MagicMock(),
        "trace_logger": MagicMock(),
        "behavior_router": AsyncMock(),
        "plugin_router": AsyncMock(),
        "fallback_router": MagicMock(),
        "behavior_routing_available": MagicMock(return_value=False),
        "plugin_routing_available": MagicMock(return_value=False),
    }
    dependencies.update(overrides)
    return RuntimeCompositionRoot().build_event_pipeline(
        **dependencies  # type: ignore[arg-type]
    )


def test_build_event_pipeline_creates_and_connects_default_components() -> None:
    event_queue = MagicMock()
    trace_logger = MagicMock()

    composition = _build_event_pipeline(
        event_queue=event_queue,
        trace_logger=trace_logger,
    )

    assert isinstance(composition.event_filter, DefaultEventFilter)
    assert isinstance(composition.event_prioritizer, DefaultEventPrioritizer)
    assert isinstance(composition.event_buffer, EventBuffer)
    assert isinstance(composition.event_subscriber_registry, EventSubscriberRegistry)
    assert isinstance(composition.user_input_event_logger, UserInputEventLogger)
    assert isinstance(composition.user_input_event_router, UserInputEventRouter)
    assert isinstance(composition.buffered_event_dispatcher, BufferedEventDispatcher)
    assert isinstance(
        composition.user_input_interruption_coordinator,
        UserInputInterruptionCoordinator,
    )
    assert isinstance(composition.event_type_router, EventTypeRouter)
    assert isinstance(composition.event_dispatch_processor, EventDispatchProcessor)
    assert isinstance(composition.conversation_logger, ConversationLogger)
    assert isinstance(
        composition.conversation_input_recorder,
        ConversationInputRecorder,
    )
    assert isinstance(composition.event_ingress_processor, EventIngressProcessor)

    assert (
        composition.buffered_event_dispatcher._event_buffer
        is composition.event_buffer
    )
    assert composition.buffered_event_dispatcher._event_queue is event_queue
    assert (
        composition.event_dispatch_processor._event_prioritizer
        is composition.event_prioritizer
    )
    assert (
        composition.event_dispatch_processor._buffered_event_dispatcher
        is composition.buffered_event_dispatcher
    )
    assert (
        composition.event_type_router._user_input_event_router
        is composition.user_input_event_router
    )
    assert (
        composition.event_type_router._user_input_event_logger
        is composition.user_input_event_logger
    )
    assert (
        composition.event_type_router._user_input_interruption_coordinator
        is composition.user_input_interruption_coordinator
    )
    assert (
        composition.event_ingress_processor._event_filter
        is composition.event_filter
    )
    assert (
        composition.event_ingress_processor._conversation_input_recorder
        is composition.conversation_input_recorder
    )
    assert (
        composition.event_ingress_processor._event_subscriber_registry
        is composition.event_subscriber_registry
    )
    assert (
        composition.conversation_input_recorder._conversation_logger
        is composition.conversation_logger
    )
    assert composition.user_input_event_logger._trace_logger is trace_logger
    assert composition.buffered_event_dispatcher._trace_logger is trace_logger
    assert (
        composition.user_input_interruption_coordinator._trace_logger
        is trace_logger
    )
    assert composition.event_dispatch_processor._trace_logger is trace_logger


def test_build_event_pipeline_preserves_all_injected_components() -> None:
    injected = {
        "event_filter": MagicMock(),
        "event_prioritizer": MagicMock(),
        "event_buffer": MagicMock(),
        "event_subscriber_registry": MagicMock(),
        "user_input_event_logger": MagicMock(),
        "user_input_event_router": MagicMock(),
        "buffered_event_dispatcher": MagicMock(),
        "user_input_interruption_coordinator": MagicMock(),
        "event_type_router": MagicMock(),
        "event_dispatch_processor": MagicMock(),
        "conversation_logger": MagicMock(),
        "conversation_input_recorder": MagicMock(),
        "event_ingress_processor": MagicMock(),
    }

    composition = _build_event_pipeline(**injected)

    for name, component in injected.items():
        assert getattr(composition, name) is component


def test_build_event_pipeline_supports_partial_conversation_injection() -> None:
    conversation_logger = MagicMock()
    composition = _build_event_pipeline(conversation_logger=conversation_logger)

    assert composition.conversation_logger is conversation_logger
    assert (
        composition.conversation_input_recorder._conversation_logger
        is conversation_logger
    )

    conversation_input_recorder = MagicMock()
    composition = _build_event_pipeline(
        conversation_input_recorder=conversation_input_recorder
    )

    assert composition.conversation_input_recorder is conversation_input_recorder


@pytest.mark.asyncio
async def test_build_event_pipeline_passes_routing_callbacks_without_eager_checks() -> (
    None
):
    behavior_router = AsyncMock()
    plugin_router = AsyncMock()
    fallback_router = MagicMock()
    behavior_routing_available = MagicMock(return_value=True)
    plugin_routing_available = MagicMock(return_value=True)
    composition = _build_event_pipeline(
        behavior_router=behavior_router,
        plugin_router=plugin_router,
        fallback_router=fallback_router,
        behavior_routing_available=behavior_routing_available,
        plugin_routing_available=plugin_routing_available,
    )

    behavior_routing_available.assert_not_called()
    plugin_routing_available.assert_not_called()
    assert composition.user_input_event_router._behavior_router is behavior_router
    assert composition.user_input_event_router._plugin_router is plugin_router
    assert composition.user_input_event_router._fallback is fallback_router
    assert composition.event_type_router._behavior_router is behavior_router

    event = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "hello"})
    await composition.user_input_event_router.route(event)

    behavior_routing_available.assert_called_once_with()
    behavior_router.assert_awaited_once_with(event)
    plugin_routing_available.assert_not_called()

    behavior_routing_available.return_value = False
    await composition.user_input_event_router.route(event)

    assert behavior_routing_available.call_count == 2
    plugin_routing_available.assert_called_once_with()
    plugin_router.assert_awaited_once_with(event)
    fallback_router.assert_not_called()
