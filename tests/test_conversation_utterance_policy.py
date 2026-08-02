from __future__ import annotations

from app.adapters.prompt.character_prompt_builder import CharacterPromptBuilder
from app.adapters.prompt.response_validator_prompt_builder import (
    ResponseValidatorPromptBuilder,
)
from app.adapters.prompt.situation_evaluator_prompt_builder import (
    SituationEvaluatorPromptBuilder,
)
from app.domain.behavior import BehaviorPlanningContext, TargetInterest
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.conversation_utterance_policy import (
    ConversationResponseMode,
    apply_conversation_response_policy,
    decide_conversation_response_mode,
    is_low_information_acknowledgement,
)
from app.domain.response_content_plan import ResponseContentPlan


def _expansive_plan() -> ResponseContentPlan:
    return ResponseContentPlan(
        primary_desire="curiosity",
        conversation_strategies=(
            "ask_for_detail",
            "explore_related_topic",
            "self_disclose_briefly",
        ),
        value_emphases=("compassion", "honesty"),
        interpersonal_stance="supportive",
        expression_mode="open",
        self_disclosure_level="brief",
        question_budget=1,
        new_direction_budget=1,
        reasons=("test",),
    )


def _autonomy_plan() -> ResponseContentPlan:
    return ResponseContentPlan(
        primary_desire="autonomy",
        conversation_strategies=(
            "take_initiative",
            "state_choice",
            "define_next_step",
        ),
        expression_mode="open",
        question_budget=0,
        new_direction_budget=1,
        reasons=("test",),
    )


def _context(
    *,
    initiative_level: float,
    phase: str,
    speech_act: str,
    user_input: str = "こんにちは",
    drive: dict[str, float] | None = None,
    plan: ResponseContentPlan | None = None,
) -> ResponseContext:
    return ResponseContext(
        user_input=user_input,
        activity_type="conversation_with_user",
        operation=None,
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="会話を継続する",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(ResponseClaim.EXTERNAL_RESULT_OBTAINED,),
        activity_goal="ユーザー入力に応答する",
        speech_act=speech_act,
        conversation_phase=phase,
        initiative_level=initiative_level,
        drive=drive or {},
        memory={"response_content_plan": (plan or _expansive_plan()).as_context()},
    )


def _high_interest() -> tuple[TargetInterest, ...]:
    return (
        TargetInterest(
            target_type="place",
            target_id="しまなみ海道",
            interest_intensity=0.95,
            knowledge_gap=0.95,
            satiation=0.05,
            reason="場所は分かったが、景色や体験がまだ分からない",
        ),
    )


def test_target_interest_question_signal_combines_gap_and_satiation() -> None:
    interest = _high_interest()[0]

    assert interest.question_signal == 0.857375


def test_surface_acknowledgement_detector_remains_compatibility_only() -> None:
    assert is_low_information_acknowledgement("いいね。そういうの")
    assert not is_low_information_acknowledgement(
        "そうだね。でもゲームは難しい方が好き"
    )

    _, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="いいね。そういうの",
        drive={"curiosity": 0.5, "engagement": 0.5, "energy": 0.7},
    )

    assert decision.low_information_input is False


def test_situation_prompt_requires_contextual_semantic_speech_acts() -> None:
    prompt = SituationEvaluatorPromptBuilder().build(
        BehaviorPlanningContext(
            user_text="しまなみ海道だよ",
            source_event_id="event-1",
            available_capabilities=frozenset(),
            conversation_history=(
                {"role": "assistant", "text": "どこへ行ったの？"},
            ),
        )
    )

    assert "answer|acknowledgement|closing" in prompt
    assert "表面文字列、語尾、疑問符の有無だけで分類せず" in prompt
    assert "『しまなみ海道だよ』はanswer" in prompt
    assert "『今日のところはこのくらいかな』はclosing" in prompt


def test_low_initiative_greeting_selects_reaction_without_hardcoded_prohibition() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="greeting",
        conversation_phase="greeting",
        initiative_level=0.15,
        user_input="こんばんわ",
        drive={"curiosity": 0.5, "engagement": 0.5, "energy": 0.7},
    )

    assert decision.mode is ConversationResponseMode.REACT
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 0
    assert effective.self_disclosure_level == "none"
    assert effective.conversation_strategies == ("share_reaction",)


def test_semantic_acknowledgement_normally_selects_listening() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="acknowledgement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="うん。そうだね",
        drive={"curiosity": 0.5, "engagement": 0.5, "energy": 0.7},
    )

    assert decision.mode is ConversationResponseMode.LISTEN
    assert decision.low_information_input is True
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 0
    assert effective.self_disclosure_level == "none"
    assert effective.conversation_strategies == ("acknowledge_other",)


def test_global_curiosity_alone_does_not_force_question_after_acknowledgement() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="acknowledgement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="うん",
        drive={
            "curiosity": 1.0,
            "engagement": 0.8,
            "boredom": 0.0,
            "energy": 0.8,
        },
    )

    assert decision.mode is ConversationResponseMode.LISTEN
    assert effective.question_budget == 0
    assert "target_interest_can_overcome_acknowledgement_weight" not in decision.reasons


def test_target_interest_and_knowledge_gap_can_select_question_after_acknowledgement() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="acknowledgement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="うん",
        drive={
            "curiosity": 0.60,
            "engagement": 0.8,
            "boredom": 0.0,
            "energy": 0.8,
        },
        active_interests=_high_interest(),
    )

    assert decision.mode is ConversationResponseMode.ASK
    assert decision.low_information_input is True
    assert effective.question_budget == 1
    assert effective.new_direction_budget == 0
    assert effective.conversation_strategies == ("ask_for_detail",)
    assert "target_interest_can_overcome_acknowledgement_weight" in decision.reasons


def test_high_interest_without_knowledge_gap_does_not_force_question() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="acknowledgement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="うん",
        drive={"curiosity": 1.0, "engagement": 0.8, "energy": 0.8},
        active_interests=(
            TargetInterest(
                target_type="place",
                target_id="しまなみ海道",
                interest_intensity=0.95,
                knowledge_gap=0.05,
                satiation=0.90,
                reason="好きな話題だが、すでに十分に聞いた",
            ),
        ),
    )

    assert decision.mode is ConversationResponseMode.LISTEN
    assert effective.question_budget == 0


def test_semantic_answer_returns_floor_instead_of_chaining_questions() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="answer",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="海と橋が一望できるところかな",
        drive={
            "curiosity": 0.99,
            "engagement": 0.95,
            "boredom": 0.0,
            "energy": 0.8,
        },
        active_interests=_high_interest(),
    )

    assert decision.mode is not ConversationResponseMode.ASK
    assert "semantic_answer_returns_conversation_floor" in decision.reasons
    assert effective.question_budget == 0


def test_semantic_closing_prefers_closure_over_high_interest() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="closing",
        conversation_phase="winding_down",
        initiative_level=0.65,
        user_input="今日のところはこのくらいかな",
        drive={
            "curiosity": 1.0,
            "engagement": 1.0,
            "boredom": 0.0,
            "energy": 0.7,
        },
        active_interests=_high_interest(),
    )

    assert decision.mode in {
        ConversationResponseMode.LISTEN,
        ConversationResponseMode.REACT,
        ConversationResponseMode.OBSERVE,
    }
    assert "semantic_closing_supports_closure" in decision.reasons
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 0


def test_low_initiative_is_weight_not_absolute_speaking_ban() -> None:
    effective, decision = apply_conversation_response_policy(
        _autonomy_plan(),
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.20,
        user_input="この後の進め方を決めよう",
        drive={
            "curiosity": 0.2,
            "engagement": 0.4,
            "boredom": 1.0,
            "energy": 1.0,
        },
    )

    assert decision.mode is ConversationResponseMode.SPEAK
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 1


def test_semantic_question_selects_direct_answer_mode() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="question",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="今日は何がしたい",
        drive={"curiosity": 0.9},
        active_interests=_high_interest(),
    )

    assert decision.mode is ConversationResponseMode.ANSWER
    assert "semantic_question_supports_answer" in decision.reasons
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 0
    assert effective.self_disclosure_level == "none"


def test_same_semantic_structure_ignores_surface_punctuation_variation() -> None:
    first = decide_conversation_response_mode(
        _expansive_plan(),
        speech_act="answer",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="しまなみ海道だよ",
        drive={"curiosity": 0.9, "engagement": 0.8},
        active_interests=_high_interest(),
    )
    second = decide_conversation_response_mode(
        _expansive_plan(),
        speech_act="answer",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="しまなみ海道だよ？？",
        drive={"curiosity": 0.9, "engagement": 0.8},
        active_interests=_high_interest(),
    )

    assert first.mode is second.mode
    assert first.scores == second.scores


def test_character_prompt_projects_semantic_acknowledgement_decision() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(
            initiative_level=0.65,
            phase="active",
            speech_act="acknowledgement",
            user_input="うん。そうだね",
            drive={"curiosity": 0.5, "engagement": 0.5, "energy": 0.7},
        ),
        character_profile=None,
        correction=None,
    )

    assert '"mode": "listen"' in prompt
    assert '"question_budget": 0' in prompt
    assert "今回のConversation Response Modeはlisten" in prompt


def test_character_prompt_does_not_treat_global_curiosity_as_target_interest() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(
            initiative_level=0.65,
            phase="active",
            speech_act="acknowledgement",
            user_input="うん",
            drive={
                "curiosity": 1.0,
                "engagement": 0.8,
                "energy": 0.8,
            },
        ),
        character_profile=None,
        correction=None,
    )

    assert '"mode": "listen"' in prompt
    assert '"question_budget": 0' in prompt


def test_validator_uses_same_semantic_decision_as_character_prompt() -> None:
    context = _context(
        initiative_level=0.65,
        phase="active",
        speech_act="answer",
        user_input="しまなみ海道だよ",
        drive={"curiosity": 0.99, "engagement": 0.9, "energy": 0.8},
    )
    character_prompt = CharacterPromptBuilder().build(
        context,
        character_profile=None,
        correction=None,
    )
    validator_prompt = ResponseValidatorPromptBuilder().build(
        context,
        CharacterResponse(speech="海と橋を一緒に眺められるのは気持ちよさそうだね。"),
    )

    assert '"mode": "ask"' not in character_prompt
    assert '"mode": "ask"' not in validator_prompt
    assert "semantic_answer_returns_conversation_floor" in character_prompt
    assert "semantic_answer_returns_conversation_floor" in validator_prompt
