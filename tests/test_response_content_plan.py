from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.prompt.character_prompt_builder import CharacterPromptBuilder
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.drives import DriveState
from app.domain.events import AgentEvent, AgentEventType
from app.domain.response_content_plan import ResponseContentPlan
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
from app.runtime.autonomous_event_planner import AutonomousEventPlanner
from app.runtime.autonomous_plan_state import AutonomousPlanState
from app.runtime.behavior_planning_context_builder import BehaviorPlanningContextBuilder
from app.runtime.conversation_resume_state import ConversationResumeState
from app.runtime.response_content_planner import ResponseContentPlanner


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


def _behavior_builder() -> BehaviorPlanningContextBuilder:
    return BehaviorPlanningContextBuilder(
        activity_manager=_ActivityManager(),  # type: ignore[arg-type]
        agent_life_service=_AgentLifeService(),  # type: ignore[arg-type]
        plugin_manager=_PluginManager(),  # type: ignore[arg-type]
    )


def _moral_context(
    *,
    compassion: float = 0.72,
    honesty: float = 0.68,
    fairness: float = 0.66,
    rule_respect: float = 0.62,
    restraint: float = 0.70,
    empathy: float = 0.70,
    aggressive: float = 0.10,
    prosocial: float = 0.72,
) -> dict[str, object]:
    return {
        "profile": {
            "compassion": compassion,
            "honesty": honesty,
            "fairness": fairness,
            "rule_respect": rule_respect,
        },
        "state": {
            "restraint": restraint,
            "empathy_activation": empathy,
            "aggressive_impulse": aggressive,
        },
        "composite": {
            "prosocial_activation": prosocial,
            "effective_restraint": restraint,
        },
        "observation_only": True,
    }


def test_response_content_plan_round_trip_is_typed_and_bounded() -> None:
    original = ResponseContentPlan(
        primary_desire="connection",
        conversation_strategies=(
            "continue_conversation",
            "acknowledge_other",
            "ask_follow_up",
        ),
        value_emphases=("compassion", "honesty", "fairness"),
        interpersonal_stance="supportive",
        expression_mode="open",
        self_disclosure_level="none",
        question_budget=1,
        new_direction_budget=0,
        reasons=("test",),
    )

    restored = ResponseContentPlan.from_context(original.as_context())

    assert restored.primary_desire == original.primary_desire
    assert restored.conversation_strategies == original.conversation_strategies
    assert restored.value_emphases == original.value_emphases
    assert restored.question_budget == 1
    assert restored.new_direction_budget == 0
    assert restored.observation_only is True


def test_connection_and_prosocial_state_produce_supportive_content_plan() -> None:
    plan = ResponseContentPlanner().build(
        motivation={
            "primary_desire": "connection",
            "expression_strength": 0.75,
            "recommended_conversation_strategies": [
                "continue_conversation",
                "acknowledge_other",
                "ask_follow_up",
            ],
            "conflicts": [],
        },
        moral=_moral_context(),
    )

    assert plan.interpersonal_stance == "supportive"
    assert plan.expression_mode == "open"
    assert plan.question_budget == 1
    assert plan.new_direction_budget == 0
    assert "compassion" in plan.value_emphases
    assert len(plan.conversation_strategies) <= 3
    assert len(plan.value_emphases) <= 3


def test_security_conflict_and_aggression_add_calm_boundary_without_hostility() -> None:
    plan = ResponseContentPlanner().build(
        motivation={
            "primary_desire": "security",
            "expression_strength": 0.30,
            "recommended_conversation_strategies": [
                "continue_conversation",
                "acknowledge_other",
                "ask_follow_up",
            ],
            "conflicts": [
                {"reason": "connection_security_tension", "intensity": 0.8}
            ],
        },
        moral=_moral_context(aggressive=0.70, restraint=0.75),
    )

    assert plan.interpersonal_stance == "guarded"
    assert plan.expression_mode == "restrained"
    assert "slow_down" in plan.conversation_strategies
    assert "state_boundary_calmly" in plan.conversation_strategies
    assert "attack_other" not in plan.conversation_strategies
    assert plan.observation_only is True


def test_behavior_preparation_transports_plan_only_on_response_event_memory() -> None:
    prepared = _behavior_builder().build(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "今日はどうしようか"},
        )
    )

    event_memory = prepared.event.payload["memory"]
    assert isinstance(event_memory, dict)
    raw_plan = event_memory["response_content_plan"]
    plan = ResponseContentPlan.from_context(raw_plan)

    assert plan.primary_desire == prepared.context.motivation["primary_desire"]
    assert plan.observation_only is True
    assert "response_content_plan" not in prepared.context.memory


def test_same_internal_state_keeps_plan_stable_across_conversation_turns() -> None:
    builder = _behavior_builder()

    first = builder.build(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "最初の話題"},
        )
    )
    second = builder.build(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "次の話題"},
        )
    )

    first_plan = first.event.payload["memory"]["response_content_plan"]
    second_plan = second.event.payload["memory"]["response_content_plan"]
    assert first_plan == second_plan
    assert first.event.payload["text"] != second.event.payload["text"]


def test_character_prompt_projects_plan_below_facts_and_claim_boundaries() -> None:
    plan = ResponseContentPlanner().build(
        motivation={
            "primary_desire": "connection",
            "expression_strength": 0.8,
            "recommended_conversation_strategies": [
                "acknowledge_other",
                "ask_follow_up",
            ],
            "conflicts": [],
        },
        moral=_moral_context(),
    )
    context = ResponseContext(
        user_input="今日は疲れた",
        activity_type="conversation_with_user",
        operation=None,
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="会話を継続する",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(ResponseClaim.EXTERNAL_RESULT_OBTAINED,),
        activity_goal="ユーザー入力に応答する",
        memory={"response_content_plan": plan.as_context()},
    )

    prompt = CharacterPromptBuilder().build(
        context,
        character_profile=None,
        correction=None,
    )

    assert "Response Content Plan:" in prompt
    assert '"primary_desire": "connection"' in prompt
    assert "allowed_claims、forbidden_claims" in prompt
    assert "行動選択、実行許可、事実認定、権限、安全判定を変更しない" in prompt
    assert "ユーザーを採点・断罪・説教せず" in prompt
    assert "question_budgetはこの1応答" in prompt


def test_autonomous_event_contains_typed_response_content_plan_snapshot() -> None:
    planner = AutonomousEventPlanner(
        ActivityManager(),
        autonomous_activity_policy=AutonomousActivityPolicy(),
        autonomous_plan_state=AutonomousPlanState(),
        conversation_resume_state=ConversationResumeState(),
        pending_confirmation_provider=lambda: False,
        conversation_idle_timeout_seconds=30.0,
    )
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    result = planner.plan(
        AgentState(current_drive=DriveState(curiosity=0.9, energy=0.9)),
        now=now,
        awakening_completed_at=None,
        continuation_provider=lambda: None,
        autonomous_topic_provider=lambda: None,
    )

    assert result.event is not None
    memory = result.event.payload["memory"]
    assert isinstance(memory, dict)
    plan = ResponseContentPlan.from_context(memory["response_content_plan"])
    assert plan.primary_desire is not None
    assert plan.observation_only is True
    assert len(plan.conversation_strategies) <= 3
    assert plan.question_budget <= 1
    assert plan.new_direction_budget <= 1
