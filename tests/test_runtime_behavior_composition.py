from queue import Queue
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_switch_coordinator import ActivitySwitchCoordinator
from app.runtime.behavior_planning_context_builder import (
    BehaviorPlanningContextBuilder,
)
from app.runtime.behavior_routing_coordinator import BehaviorRoutingCoordinator
from app.runtime.behavior_routing_support import BehaviorFallbackRouter
from app.runtime.confirmation_coordinator import ConfirmationCoordinator
from app.runtime.explicit_activity_executor import ExplicitActivityExecutor
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.pending_confirmation import ConfirmationResolver
from app.runtime.plugin_activity_coordinator import PluginActivityCoordinator
from app.runtime.plugin_ongoing_activity_synchronizer import (
    PluginOngoingActivitySynchronizer,
)
from app.runtime.runtime_composition_root import RuntimeCompositionRoot
from app.runtime.runtime_coordinator import RuntimeCoordinator

pytestmark = pytest.mark.unit


def _build_behavior(**overrides: object):
    dependencies = {
        "activity_manager": MagicMock(),
        "action_planner": MagicMock(),
        "action_scheduler": MagicMock(),
        "agent_life_service": MagicMock(),
        "plugin_manager": MagicMock(),
        "behavior_planner": MagicMock(),
        "activity_plan_validator": MagicMock(),
        "activity_registry": MagicMock(),
        "pending_confirmation_manager": MagicMock(),
        "short_term_memory": MagicMock(),
        "topic_history": MagicMock(),
        "trace_logger": MagicMock(),
        "plugin_router": AsyncMock(),
        "execution_fallback": MagicMock(),
        "current_ongoing_activity": MagicMock(return_value=None),
    }
    dependencies.update(overrides)
    return RuntimeCompositionRoot().build_behavior_composition(
        **dependencies  # type: ignore[arg-type]
    )


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


def test_build_behavior_composition_creates_and_connects_default_components() -> None:
    activity_manager = MagicMock()
    trace_logger = MagicMock()
    plugin_router = AsyncMock()
    execution_fallback = MagicMock()
    current_ongoing_activity = MagicMock(return_value=None)

    composition = _build_behavior(
        activity_manager=activity_manager,
        trace_logger=trace_logger,
        plugin_router=plugin_router,
        execution_fallback=execution_fallback,
        current_ongoing_activity=current_ongoing_activity,
    )

    assert isinstance(composition.confirmation_resolver, ConfirmationResolver)
    assert isinstance(
        composition.ongoing_activity_coordinator,
        OngoingActivityCoordinator,
    )
    assert isinstance(composition.behavior_fallback_router, BehaviorFallbackRouter)
    assert isinstance(composition.confirmation_coordinator, ConfirmationCoordinator)
    assert isinstance(
        composition.plugin_ongoing_activity_synchronizer,
        PluginOngoingActivitySynchronizer,
    )
    assert isinstance(
        composition.behavior_planning_context_builder,
        BehaviorPlanningContextBuilder,
    )
    assert isinstance(
        composition.explicit_activity_executor,
        ExplicitActivityExecutor,
    )
    assert isinstance(
        composition.plugin_activity_coordinator,
        PluginActivityCoordinator,
    )
    assert isinstance(
        composition.activity_switch_coordinator,
        ActivitySwitchCoordinator,
    )
    assert isinstance(
        composition.behavior_routing_coordinator,
        BehaviorRoutingCoordinator,
    )

    synchronizer = composition.plugin_ongoing_activity_synchronizer
    plugin_activity = composition.plugin_activity_coordinator
    activity_switch = composition.activity_switch_coordinator
    routing = composition.behavior_routing_coordinator
    fallback = composition.behavior_fallback_router

    assert synchronizer._ongoing is composition.ongoing_activity_coordinator
    assert plugin_activity._ongoing_synchronizer is synchronizer
    assert (
        plugin_activity._explicit_activity_executor
        is composition.explicit_activity_executor
    )
    assert plugin_activity._execution_fallback is execution_fallback
    assert activity_switch._execution_fallback is execution_fallback
    assert activity_switch._plugin_router is plugin_router
    assert activity_switch._current_ongoing_activity is current_ongoing_activity
    assert routing._context_builder is composition.behavior_planning_context_builder
    assert routing._confirmation is composition.confirmation_coordinator
    assert routing._plugin_activity is plugin_activity
    assert routing._activity_switch is activity_switch
    assert routing._fallback is fallback
    assert plugin_activity._conversation_fallback.__self__ is fallback
    assert (
        composition.confirmation_coordinator._conversation_fallback.__self__
        is fallback
    )
    assert synchronizer._trace_logger is trace_logger
    assert plugin_activity._trace_logger is trace_logger
    assert activity_switch._trace_logger is trace_logger
    assert routing._trace_logger is trace_logger


def test_build_behavior_composition_preserves_all_injected_components() -> None:
    injected = {
        "confirmation_resolver": MagicMock(),
        "confirmation_coordinator": MagicMock(),
        "plugin_ongoing_activity_synchronizer": MagicMock(),
        "behavior_planning_context_builder": MagicMock(),
        "explicit_activity_executor": MagicMock(),
        "plugin_activity_coordinator": MagicMock(),
        "activity_switch_coordinator": MagicMock(),
        "behavior_routing_coordinator": MagicMock(),
    }

    composition = _build_behavior(**injected)

    for name, component in injected.items():
        assert getattr(composition, name) is component


@pytest.mark.parametrize(
    "injected_name",
    [
        "confirmation_resolver",
        "confirmation_coordinator",
        "plugin_ongoing_activity_synchronizer",
        "behavior_planning_context_builder",
        "explicit_activity_executor",
        "plugin_activity_coordinator",
        "activity_switch_coordinator",
        "behavior_routing_coordinator",
    ],
)
def test_build_behavior_composition_preserves_partial_injection(
    injected_name: str,
) -> None:
    injected = MagicMock()

    composition = _build_behavior(**{injected_name: injected})

    assert getattr(composition, injected_name) is injected
    assert isinstance(composition.behavior_fallback_router, BehaviorFallbackRouter)
    assert isinstance(
        composition.ongoing_activity_coordinator,
        OngoingActivityCoordinator,
    )


@pytest.mark.parametrize(
    ("manager_present", "validator_present", "created"),
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_confirmation_coordinator_creation_requires_manager_and_validator(
    manager_present: bool,
    validator_present: bool,
    created: bool,
) -> None:
    composition = _build_behavior(
        pending_confirmation_manager=MagicMock() if manager_present else None,
        activity_plan_validator=MagicMock() if validator_present else None,
    )

    assert (composition.confirmation_coordinator is not None) is created


def test_injected_confirmation_coordinator_is_preserved_without_dependencies() -> None:
    confirmation_coordinator = MagicMock()

    composition = _build_behavior(
        pending_confirmation_manager=None,
        activity_plan_validator=None,
        confirmation_coordinator=confirmation_coordinator,
    )

    assert composition.confirmation_coordinator is confirmation_coordinator


def test_context_builder_creation_depends_on_plugin_manager() -> None:
    without_plugins = _build_behavior(plugin_manager=None)
    with_plugins = _build_behavior(plugin_manager=MagicMock())

    assert without_plugins.behavior_planning_context_builder is None
    assert isinstance(
        with_plugins.behavior_planning_context_builder,
        BehaviorPlanningContextBuilder,
    )


def test_current_ongoing_activity_is_evaluated_lazily() -> None:
    state = {"activity": MagicMock()}
    composition = _build_behavior(
        current_ongoing_activity=lambda: state["activity"],
    )
    replacement = MagicMock()

    state["activity"] = replacement

    assert (
        composition.activity_switch_coordinator._current_ongoing_activity()
        is replacement
    )


def test_runtime_coordinator_builds_behavior_components_and_shares_ongoing() -> None:
    coordinator = _build_coordinator()

    assert isinstance(coordinator._behavior_fallback_router, BehaviorFallbackRouter)
    assert isinstance(
        coordinator._ongoing_activity_coordinator,
        OngoingActivityCoordinator,
    )
    assert coordinator._behavior_planning_context_builder is None
    assert (
        coordinator._plugin_ongoing_activity_synchronizer._ongoing
        is coordinator._ongoing_activity_coordinator
    )
    assert (
        coordinator._runtime_host_controller._ongoing
        is coordinator._ongoing_activity_coordinator
    )


def test_runtime_coordinator_preserves_injected_behavior_components() -> None:
    injected = {
        "confirmation_resolver": MagicMock(),
        "confirmation_coordinator": MagicMock(),
        "plugin_ongoing_activity_synchronizer": MagicMock(),
        "behavior_planning_context_builder": MagicMock(),
        "explicit_activity_executor": MagicMock(),
        "plugin_activity_coordinator": MagicMock(),
        "activity_switch_coordinator": MagicMock(),
        "behavior_routing_coordinator": MagicMock(),
    }

    coordinator = _build_coordinator(**injected)

    for name, component in injected.items():
        assert getattr(coordinator, f"_{name}") is component


@pytest.mark.asyncio
async def test_runtime_coordinator_routes_through_resolved_behavior_coordinator() -> None:
    behavior_routing_coordinator = MagicMock()
    behavior_routing_coordinator.route = AsyncMock(return_value=None)
    coordinator = _build_coordinator(
        behavior_routing_coordinator=behavior_routing_coordinator
    )
    event = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "hi"})

    result = await coordinator._route_behavior(event)

    assert result is None
    behavior_routing_coordinator.route.assert_awaited_once_with(event)
