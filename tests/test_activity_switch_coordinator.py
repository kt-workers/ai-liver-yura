import pytest

from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
)
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_switch_coordinator import ActivitySwitchCoordinator
from app.runtime.behavior_planner import ActivityPlanValidator
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


def _current_definition() -> ActivityDefinition:
    return ActivityDefinition(
        activity_type="shiritori",
        display_name="しりとり",
        required_capability="games.shiritori",
        provider_plugin_id="games",
        supported_operations=(
            ActivityOperation.START,
            ActivityOperation.CONTINUE,
            ActivityOperation.STOP,
        ),
    )


def _target_plan() -> ActivityPlan:
    return ActivityPlan(
        decision=BehaviorDecision.SWITCH_ACTIVITY,
        activity_type="quiz",
        goal="クイズへ切り替える",
        required_capability="games.quiz",
        provider_plugin_id="quiz",
        operation=ActivityOperation.START,
        requested_new_activity="quiz",
        confidence=0.9,
    )


def _context() -> BehaviorPlanningContext:
    definition = _current_definition()
    return BehaviorPlanningContext(
        user_text="クイズにしよう",
        source_event_id="event-switch",
        available_capabilities=frozenset(
            {"games.shiritori", "games.quiz"},
        ),
        active_activity_definition=definition,
        activity_definitions=(definition,),
    )


def _event() -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "クイズにしよう"},
    )


def _fallback(
    event: AgentEvent,
    contexts: list[dict[str, object]],
    reason: str,
    confidence: float,
) -> AgentEvent:
    del contexts, confidence
    return AgentEvent(
        event_type=event.event_type,
        payload={**event.payload, "execution_match_reason": reason},
        trace_context=event.trace_context,
    )


@pytest.mark.asyncio
async def test_stop_rejection_never_calls_plugin_router() -> None:
    calls: list[str] = []

    async def router(*_args: object, **_kwargs: object) -> None:
        calls.append("unexpected")

    coordinator = ActivitySwitchCoordinator(
        validator=ActivityPlanValidator(lambda *_: False),
        plugin_router=router,
        current_ongoing_activity=lambda: None,
        execution_fallback=_fallback,
        trace_logger=TraceLogger(),
    )

    routed = await coordinator.route(_event(), _target_plan(), _context())

    assert routed is not None
    assert routed.payload["execution_match_reason"] == "switch_stop_rejected"
    assert calls == []


@pytest.mark.asyncio
async def test_stop_failure_does_not_start_target_activity() -> None:
    calls: list[str] = []
    event = _event()

    async def router(
        routed_event: AgentEvent,
        **kwargs: object,
    ) -> AgentEvent | None:
        plan = kwargs["activity_plan"]
        assert isinstance(plan, ActivityPlan)
        assert plan.operation is not None
        calls.append(plan.operation.value)
        return routed_event

    coordinator = ActivitySwitchCoordinator(
        validator=ActivityPlanValidator(lambda *_: True),
        plugin_router=router,
        current_ongoing_activity=lambda: None,
        execution_fallback=_fallback,
        trace_logger=TraceLogger(),
    )

    routed = await coordinator.route(event, _target_plan(), _context())

    assert routed is not None
    assert routed.payload["execution_match_reason"] == "switch_stop_failed"
    assert calls == ["stop"]


@pytest.mark.asyncio
async def test_target_starts_only_after_stop_completed() -> None:
    calls: list[str] = []
    ongoing = {"active": True}

    async def router(
        _event: AgentEvent,
        **kwargs: object,
    ) -> None:
        plan = kwargs["activity_plan"]
        assert isinstance(plan, ActivityPlan)
        assert plan.operation is not None
        calls.append(plan.operation.value)
        if plan.operation == ActivityOperation.STOP:
            ongoing["active"] = False

    coordinator = ActivitySwitchCoordinator(
        validator=ActivityPlanValidator(lambda *_: True),
        plugin_router=router,
        current_ongoing_activity=lambda: (
            object() if ongoing["active"] else None  # type: ignore[return-value]
        ),
        execution_fallback=_fallback,
        trace_logger=TraceLogger(),
    )

    routed = await coordinator.route(_event(), _target_plan(), _context())

    assert routed is None
    assert calls == ["stop", "start"]
