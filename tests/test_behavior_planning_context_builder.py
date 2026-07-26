from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_state import AgentState
from app.runtime.behavior_planning_context_builder import (
    BehaviorPlanningContextBuilder,
)


class _ActivityManager:
    ongoing_activity = None
    last_activity_result = None


class _AgentLifeService:
    agent_state = AgentState()

    def preview_relationship(self, event: AgentEvent) -> None:
        return None


class _PluginManager:
    def list_capabilities(self) -> tuple[str, ...]:
        return ("conversation",)

    def list_activity_definitions(self) -> tuple[object, ...]:
        return ()

    def active_activity_definition(self) -> None:
        return None


class _ActivityRegistry:
    def __init__(self, definitions: tuple[object, ...]) -> None:
        self._definitions = definitions

    def list_definitions(self) -> tuple[object, ...]:
        return self._definitions


def _builder(*, activity_registry: object | None = None) -> BehaviorPlanningContextBuilder:
    return BehaviorPlanningContextBuilder(
        activity_manager=_ActivityManager(),  # type: ignore[arg-type]
        agent_life_service=_AgentLifeService(),  # type: ignore[arg-type]
        plugin_manager=_PluginManager(),  # type: ignore[arg-type]
        activity_registry=activity_registry,  # type: ignore[arg-type]
    )


def test_build_enriches_user_event_and_creates_planning_context() -> None:
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )

    prepared = _builder().build(event)

    assert prepared.event is not event
    assert prepared.event.payload["input_authority"] == {
        "role": event.authority.role,
        "instruction_trusted": event.authority.instruction_trusted,
    }
    assert prepared.event.payload["conversation_history"] == ()
    assert prepared.event.payload["related_knowledge"] == ()
    assert prepared.context.user_text == "こんにちは"
    assert prepared.context.source_event_id == event.event_id
    assert prepared.context.event_type == AgentEventType.USER_TEXT.value
    assert prepared.context.available_capabilities == ("conversation",)
    assert prepared.context.trace_context == event.trace_context
    assert prepared.ongoing_activity is None


def test_app_started_uses_runtime_startup_activity_definition() -> None:
    event = AgentEvent(event_type=AgentEventType.APP_STARTED, payload={})

    prepared = _builder(
        activity_registry=_ActivityRegistry((object(),))
    ).build(event)

    definitions = prepared.context.activity_definitions
    assert len(definitions) == 1
    assert definitions[0].activity_type == "awakening"
    assert definitions[0].provider_plugin_id == "runtime"
    assert prepared.context.request_kind is None


def test_registry_definitions_are_used_for_normal_events() -> None:
    definition = BehaviorPlanningContextBuilder.startup_activity_definition()
    event = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "話そう"})

    prepared = _builder(
        activity_registry=_ActivityRegistry((definition,))
    ).build(event)

    assert prepared.context.activity_definitions == (definition,)


def test_ongoing_planning_context_returns_none_without_activity() -> None:
    assert BehaviorPlanningContextBuilder.ongoing_planning_context(None) is None
