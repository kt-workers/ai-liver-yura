from dataclasses import dataclass

import pytest

from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.behavior_planner import ActivityPlanValidator
from app.runtime.behavior_planning_context_builder import (
    BehaviorPlanningPreparation,
)
from app.runtime.behavior_routing_coordinator import BehaviorRoutingCoordinator
from app.runtime.behavior_routing_support import BehaviorFallbackRouter
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


class FakePluginManager:
    def list_capabilities(self) -> frozenset[str]:
        return frozenset({"games.test"})


@dataclass
class FakeContextBuilder:
    def build(self, event: AgentEvent) -> BehaviorPlanningPreparation:
        return BehaviorPlanningPreparation(
            event=event,
            context=BehaviorPlanningContext(
                user_text=str(event.payload.get("text") or ""),
                source_event_id=event.event_id,
                available_capabilities=frozenset({"games.test"}),
                trace_context=event.trace_context,
            ),
            ongoing_activity=None,
        )


class FakePlanner:
    def __init__(self, plan: ActivityPlan) -> None:
        self._plan = plan
        self.evaluate_calls = 0

    async def evaluate_situation(
        self,
        context: BehaviorPlanningContext,
    ) -> SituationAnalysis:
        del context
        self.evaluate_calls += 1
        return SituationAnalysis(
            activity_candidate=self._plan.activity_type,
            operation=self._plan.operation,
            goal=self._plan.goal,
            confidence=self._plan.confidence,
            reason="test_situation",
        )

    async def plan(
        self,
        context: BehaviorPlanningContext,
        situation: SituationAnalysis,
    ) -> ActivityPlan:
        del context, situation
        return self._plan

    def fallback_after_rejection(self, _evaluation: object) -> ActivityPlan:
        return ActivityPlan(
            decision=BehaviorDecision.CONVERSATION,
            activity_type="conversation",
            goal="通常会話へ戻る",
            operation=ActivityOperation.DISCUSS,
            reason="test_fallback",
        )


class FakeConfirmation:
    def __init__(self) -> None:
        self.requested = False

    def route_pending(self, *_args: object) -> None:
        return None

    def request_confirmation(
        self,
        event: AgentEvent,
        plan: ActivityPlan,
        **_kwargs: object,
    ) -> AgentEvent:
        self.requested = True
        return AgentEvent(
            event_type=event.event_type,
            payload={**event.payload, "confirmation_requested": plan.activity_type},
            trace_context=event.trace_context,
        )


class FakePluginActivity:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def route(
        self,
        event: AgentEvent,
        **kwargs: object,
    ) -> AgentEvent:
        plan = kwargs["activity_plan"]
        assert isinstance(plan, ActivityPlan)
        self.calls.append(plan.activity_type)
        return event


class FakeActivitySwitch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def route(
        self,
        event: AgentEvent,
        plan: ActivityPlan,
        _context: BehaviorPlanningContext,
    ) -> AgentEvent:
        self.calls.append(plan.activity_type)
        return event


def _event(event_type: AgentEventType = AgentEventType.USER_TEXT) -> AgentEvent:
    return AgentEvent(event_type=event_type, payload={"text": "テスト"})


def _plan(
    *,
    decision: BehaviorDecision = BehaviorDecision.CONVERSATION,
    capability: str | None = None,
) -> ActivityPlan:
    return ActivityPlan(
        decision=decision,
        activity_type=(
            "conversation"
            if decision == BehaviorDecision.CONVERSATION
            else "test_activity"
        ),
        goal="テストする",
        required_capability=capability,
        provider_plugin_id="test" if capability else None,
        operation=(
            ActivityOperation.DISCUSS
            if decision == BehaviorDecision.CONVERSATION
            else ActivityOperation.START
        ),
        requested_new_activity=(
            "test_activity"
            if decision == BehaviorDecision.SWITCH_ACTIVITY
            else None
        ),
        confidence=0.9,
        reason="test_plan",
    )


def _coordinator(
    plan: ActivityPlan,
    *,
    capability_available: bool = True,
) -> tuple[
    BehaviorRoutingCoordinator,
    FakePlanner,
    FakeConfirmation,
    FakePluginActivity,
    FakeActivitySwitch,
]:
    manager = FakePluginManager()
    planner = FakePlanner(plan)
    confirmation = FakeConfirmation()
    plugin = FakePluginActivity()
    switch = FakeActivitySwitch()
    trace_logger = TraceLogger()
    coordinator = BehaviorRoutingCoordinator(
        planner=planner,  # type: ignore[arg-type]
        validator=ActivityPlanValidator(lambda *_: capability_available),
        plugin_manager=manager,  # type: ignore[arg-type]
        context_builder=FakeContextBuilder(),  # type: ignore[arg-type]
        confirmation_coordinator=confirmation,  # type: ignore[arg-type]
        plugin_activity_coordinator=plugin,  # type: ignore[arg-type]
        activity_switch_coordinator=switch,  # type: ignore[arg-type]
        fallback_router=BehaviorFallbackRouter(
            plugin_manager=manager,  # type: ignore[arg-type]
            trace_logger=trace_logger,
        ),
        trace_logger=trace_logger,
    )
    return coordinator, planner, confirmation, plugin, switch


@pytest.mark.asyncio
async def test_app_started_uses_runtime_plan_without_planner_evaluation() -> None:
    coordinator, planner, *_ = _coordinator(_plan())

    routed = await coordinator.route(_event(AgentEventType.APP_STARTED))

    assert routed is not None
    assert planner.evaluate_calls == 0
    assert routed.payload["behavior_plan"]["activity_type"] == "awakening"
    assert routed.payload["situation_analysis"] == {
        "event_type": "app_started",
        "lifecycle_phase": "awakening",
        "speech_required": False,
    }


@pytest.mark.asyncio
async def test_ask_confirmation_delegates_and_updates_read_only_state() -> None:
    plan = _plan(
        decision=BehaviorDecision.ASK_CONFIRMATION,
        capability="games.test",
    )
    coordinator, _, confirmation, *_ = _coordinator(plan)

    routed = await coordinator.route(_event())

    assert routed is not None
    assert routed.payload["confirmation_requested"] == "test_activity"
    assert confirmation.requested is True
    assert coordinator.last_evaluation is not None
    assert coordinator.last_fallback_plan is None


@pytest.mark.asyncio
async def test_rejected_plan_returns_fallback_with_compatible_payload() -> None:
    coordinator, *_ = _coordinator(
        _plan(
            decision=BehaviorDecision.START_ACTIVITY,
            capability="games.test",
        ),
        capability_available=False,
    )

    routed = await coordinator.route(_event())

    assert routed is not None
    assert coordinator.last_evaluation is not None
    assert coordinator.last_evaluation.accepted is False
    assert coordinator.last_fallback_plan is not None
    assert routed.payload["execution_match_reason"] == "activity_capability_rejected"
    assert "behavior_plan" in routed.payload
    assert "behavior_plan_result" in routed.payload
    assert "behavior_fallback_plan" in routed.payload
    assert "activity_execution_result" in routed.payload


@pytest.mark.asyncio
async def test_conversation_route_preserves_behavior_and_trace_payload() -> None:
    coordinator, *_ = _coordinator(_plan())
    event = _event()

    routed = await coordinator.route(event)

    assert routed is not None
    plan_payload = routed.payload["behavior_plan"]
    assert plan_payload["decision"] == "conversation"
    assert routed.payload["available_plugin_capabilities"] == ["games.test"]
    assert routed.payload["activity_execution_result"].status.value == "waiting_input"
    trace = routed.payload["trace_context"]
    assert trace.trace_id == event.trace_context.trace_id
    assert trace.behavior_plan_id == plan_payload["behavior_plan_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected_owner"),
    [
        (BehaviorDecision.START_ACTIVITY, "plugin"),
        (BehaviorDecision.SWITCH_ACTIVITY, "switch"),
    ],
)
async def test_execution_branches_delegate_to_specialized_coordinator(
    decision: BehaviorDecision,
    expected_owner: str,
) -> None:
    coordinator, _, _, plugin, switch = _coordinator(
        _plan(decision=decision, capability="games.test"),
    )

    routed = await coordinator.route(_event())

    assert routed is not None
    assert plugin.calls == (["test_activity"] if expected_owner == "plugin" else [])
    assert switch.calls == (["test_activity"] if expected_owner == "switch" else [])
