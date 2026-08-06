from datetime import datetime, timezone

from app.domain.autonomous_interaction import AutonomousInteractionAction
from app.domain.desires import DesireState, DesireType
from app.domain.drives import DriveState
from app.domain.interaction_intention import InteractionIntentionType
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
from app.runtime.autonomous_event_planner import AutonomousEventPlanner
from app.runtime.autonomous_interaction_decider import AutonomousInteractionDecider
from app.runtime.autonomous_motivation_context import AutonomousMotivationContextBuilder
from app.runtime.autonomous_plan_state import AutonomousPlanState
from app.runtime.conversation_resume_state import ConversationResumeState


def _motivation(state: AgentState) -> dict[str, object]:
    return AutonomousMotivationContextBuilder().build(state)


def _decide(state: AgentState):
    return AutonomousInteractionDecider().decide(
        state,
        motivation=_motivation(state),
        continuation_result=None,
        autonomous_topic=None,
        resume_reason="no_conversation",
        is_autonomous_lookahead=False,
    )


def _planner() -> AutonomousEventPlanner:
    return AutonomousEventPlanner(
        ActivityManager(),
        autonomous_activity_policy=AutonomousActivityPolicy(),
        autonomous_plan_state=AutonomousPlanState(),
        conversation_resume_state=ConversationResumeState(),
        pending_confirmation_provider=lambda: False,
        conversation_idle_timeout_seconds=30.0,
    )


def _plan(state: AgentState):
    return _planner().plan(
        state,
        now=datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc),
        awakening_completed_at=None,
        continuation_provider=lambda: None,
        autonomous_topic_provider=lambda: None,
    )


def test_curiosity_starts_share_without_authorizing_unsolicited_question() -> None:
    state = AgentState(
        current_drive=DriveState(
            curiosity=0.90,
            engagement=0.60,
            boredom=0.10,
            energy=0.90,
        )
    )

    decision, comparison = _decide(state)

    assert decision.action is AutonomousInteractionAction.START
    assert (
        decision.interaction_intention.intention
        is InteractionIntentionType.SHARE
    )
    assert decision.interaction_intention.intention is not InteractionIntentionType.ASK
    assert decision.interaction_intention.observation_only is False
    assert comparison.matched is True
    assert comparison.conservative_start_allowed is True


def test_boredom_alone_cannot_claim_the_conversation_turn() -> None:
    state = AgentState(
        current_drive=DriveState(
            curiosity=0.50,
            engagement=0.40,
            boredom=0.92,
            energy=0.90,
        )
    )

    decision, comparison = _decide(state)
    result = _plan(state)

    assert decision.action is AutonomousInteractionAction.OBSERVE
    assert (
        decision.interaction_intention.intention
        is InteractionIntentionType.OBSERVE
    )
    assert comparison.legacy_drive_ready is True
    assert comparison.causal_vetoed_legacy_start is True
    assert result.event is None
    assert result.skip_reason == "interaction_intention_wait"
    assert result.details["causal_vetoed_legacy_start"] is True


def test_causal_start_does_not_expand_beyond_legacy_gate_during_migration() -> None:
    initial = DesireState()
    desire = initial.with_value(
        DesireType.EXPRESSION,
        initial.expression.adjusted(level_delta=0.55),
    )
    state = AgentState(
        current_desire=desire,
        current_drive=DriveState(
            curiosity=0.20,
            engagement=0.30,
            boredom=0.10,
            energy=0.90,
        ),
    )

    decision, comparison = _decide(state)
    result = _plan(state)

    assert decision.action is AutonomousInteractionAction.START
    assert comparison.legacy_drive_ready is False
    assert comparison.expansion_blocked is True
    assert comparison.conservative_start_allowed is False
    assert result.event is None
    assert result.skip_reason == "drive_too_weak"
    assert result.details["expansion_blocked"] is True


def test_security_motivation_vetoes_legacy_drive_start() -> None:
    initial = DesireState()
    desire = initial.with_value(
        DesireType.SECURITY,
        initial.security.adjusted(level_delta=0.60),
    )
    state = AgentState(
        current_desire=desire,
        current_drive=DriveState(
            curiosity=0.90,
            engagement=0.50,
            boredom=0.20,
            energy=0.90,
        ),
    )

    decision, comparison = _decide(state)

    assert decision.action is AutonomousInteractionAction.WAIT
    assert (
        decision.interaction_intention.intention
        is InteractionIntentionType.PAUSE
    )
    assert comparison.causal_vetoed_legacy_start is True


def test_planned_event_contains_adopted_interaction_intention_and_comparison() -> None:
    state = AgentState(
        current_drive=DriveState(curiosity=0.90, energy=0.90)
    )

    result = _plan(state)

    assert result.event is not None
    intention = result.event.payload["interaction_intention"]
    decision = result.event.payload["autonomous_start_decision"]
    comparison = result.event.payload["autonomous_start_comparison"]
    assert isinstance(intention, dict)
    assert intention["intention"] == "share"
    assert intention["observation_only"] is False
    assert isinstance(decision, dict)
    assert decision["action"] == "start"
    assert isinstance(comparison, dict)
    assert comparison["conservative_start_allowed"] is True
