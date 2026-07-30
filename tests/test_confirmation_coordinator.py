from dataclasses import asdict

import pytest

from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
)
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.behavior_planner import ActivityPlanValidator
from app.runtime.confirmation_coordinator import ConfirmationCoordinator
from app.runtime.pending_confirmation import (
    ConfirmationResolver,
    PendingConfirmationManager,
)
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


def _plan_payload(plan: ActivityPlan) -> dict[str, object]:
    payload = asdict(plan)
    payload["decision"] = plan.decision.value
    payload["operation"] = plan.operation.value if plan.operation else None
    payload["speech_act"] = plan.speech_act.value
    payload["ongoing_input_decision"] = (
        plan.ongoing_input_decision.value
        if plan.ongoing_input_decision is not None
        else None
    )
    return payload


def _plan() -> ActivityPlan:
    return ActivityPlan(
        decision=BehaviorDecision.ASK_CONFIRMATION,
        activity_type="echo_activity",
        goal="海の生き物縛りのエコー活動を開始する",
        required_capability="sample.echo",
        provider_plugin_id="sample",
        operation=ActivityOperation.START,
        constraints={"theme": "海の生き物"},
        confidence=0.6,
        reason="semantic_confidence_below_threshold",
    )


def _coordinator(
    manager: PendingConfirmationManager | None = None,
) -> ConfirmationCoordinator:
    return ConfirmationCoordinator(
        manager=manager or PendingConfirmationManager(),
        resolver=ConfirmationResolver(),
        validator=ActivityPlanValidator(lambda *_: True),
        conversation_fallback=lambda event: event,
        plan_payload=_plan_payload,
        trace_logger=TraceLogger(),
    )


def _event(text: str) -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": text},
    )


def _context(event: AgentEvent, text: str) -> BehaviorPlanningContext:
    return BehaviorPlanningContext(
        user_text=text,
        source_event_id=event.event_id,
        available_capabilities=frozenset({"sample.echo"}),
        trace_context=event.trace_context,
    )


def _request(coordinator: ConfirmationCoordinator) -> tuple[AgentEvent, str]:
    event = _event("エコー活動を始める？")
    routed = coordinator.request_confirmation(
        event,
        _plan(),
        current_ongoing_activity_id=None,
        situation_payload={"confidence": 0.6},
    )
    pending = coordinator.pending
    assert pending is not None
    payload = routed.payload["pending_confirmation"]
    assert isinstance(payload, dict)
    assert payload["attempt_count"] == 0
    assert payload["max_attempts"] == pending.max_attempts
    return event, pending.confirmation_id


def test_affirmative_confirmation_restores_snapshot_and_inherits_trace() -> None:
    coordinator = _coordinator()
    original_event, confirmation_id = _request(coordinator)
    answer = _event("はい")

    result = coordinator.route_pending(answer, _context(answer, "はい"))

    assert result is not None
    assert result.terminal_event is None
    assert result.plan is not None
    assert result.plan.decision == BehaviorDecision.START_ACTIVITY
    assert result.plan.confidence == 1.0
    assert result.situation_payload == {"confidence": 0.6}
    assert result.event.trace_context.parent_trace_id == (
        original_event.trace_context.trace_id
    )
    assert result.event.trace_context.confirmation_id == confirmation_id
    payload = result.confirmation_payload["pending_confirmation"]
    assert isinstance(payload, dict)
    assert payload["resolution"] == "affirmative"
    assert payload["resolution_trace_id"] == answer.trace_context.trace_id
    assert payload["final_behavior_plan_id"] == (
        f"{confirmation_id}:{answer.event_id}"
    )


@pytest.mark.parametrize(
    ("text", "resolution", "summary"),
    [
        ("いいえ", "negative", "確認候補は実行せず、現在の状態を維持する"),
        ("確認はいい", "cancel", "確認を取り消し、候補は実行しない"),
    ],
)
def test_negative_and_cancel_are_terminal_without_executing_candidate(
    text: str,
    resolution: str,
    summary: str,
) -> None:
    coordinator = _coordinator()
    _request(coordinator)
    answer = _event(text)

    result = coordinator.route_pending(answer, _context(answer, text))

    assert result is not None
    assert result.plan is None
    assert result.terminal_event is not None
    execution = result.terminal_event.payload["activity_execution_result"]
    assert execution.status.value == "canceled"
    assert execution.failure_reason == resolution
    assert execution.payload["summary"] == summary
    assert coordinator.pending is None


def test_revision_updates_candidate_and_keeps_confirmation_waiting() -> None:
    coordinator = _coordinator()
    _request(coordinator)
    answer = _event("うん、でもテーマは深海生物にして")

    result = coordinator.route_pending(
        answer,
        _context(answer, "うん、でもテーマは深海生物にして"),
    )

    assert result is not None
    assert result.terminal_event is not None
    pending = coordinator.pending
    assert pending is not None
    assert pending.attempt_count == 1
    assert pending.candidate_constraints["theme"] == "深海生物"
    payload = result.terminal_event.payload["pending_confirmation"]
    assert payload["resolution"] == "clarification"
    assert payload["attempt_count"] == 1


def test_max_attempts_ends_confirmation_with_compatible_payload() -> None:
    coordinator = _coordinator(PendingConfirmationManager(max_attempts=1))
    _request(coordinator)
    answer = _event("たぶん")

    result = coordinator.route_pending(answer, _context(answer, "たぶん"))

    assert result is not None
    assert result.terminal_event is not None
    assert coordinator.pending is None
    payload = result.terminal_event.payload["pending_confirmation"]
    assert payload["resolution"] == "max_attempts_reached"
    assert payload["attempt_count"] == 0
    execution = result.terminal_event.payload["activity_execution_result"]
    assert execution.failure_reason == "max_attempts_reached"
