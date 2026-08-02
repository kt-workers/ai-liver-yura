from __future__ import annotations

from app.adapters.prompt.character_prompt_builder import CharacterPromptBuilder
from app.adapters.prompt.response_validator_prompt_builder import (
    ResponseValidatorPromptBuilder,
)
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


def test_compound_acknowledgement_is_detected_without_consuming_substantive_text() -> None:
    assert is_low_information_acknowledgement("いいね。そういうの")
    assert is_low_information_acknowledgement("前向きでいいね")
    assert not is_low_information_acknowledgement(
        "そうだね。でもゲームは難しい方が好き"
    )
    assert not is_low_information_acknowledgement("いいね。どこから始める？")


def test_low_initiative_greeting_selects_reaction_without_hardcoded_prohibition() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="greeting",
        conversation_phase="greeting",
        initiative_level=0.15,
        user_input="こんにちは",
        drive={"curiosity": 0.5, "engagement": 0.5, "energy": 0.7},
    )

    assert decision.mode is ConversationResponseMode.REACT
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 0
    assert effective.self_disclosure_level == "none"
    assert effective.conversation_strategies == ("share_reaction",)
    assert "conversation_response_mode:react" in effective.reasons


def test_acknowledgement_normally_selects_listening() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="いいね。そういうの",
        drive={"curiosity": 0.5, "engagement": 0.5, "energy": 0.7},
    )

    assert decision.mode is ConversationResponseMode.LISTEN
    assert decision.low_information_input is True
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 0
    assert effective.self_disclosure_level == "none"
    assert effective.conversation_strategies == ("acknowledge_other",)


def test_strong_curiosity_can_select_question_even_after_acknowledgement() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="いいね。そういうの",
        drive={
            "curiosity": 0.99,
            "engagement": 0.8,
            "boredom": 0.0,
            "energy": 0.8,
        },
    )

    assert decision.mode is ConversationResponseMode.ASK
    assert decision.low_information_input is True
    assert effective.question_budget == 1
    assert effective.new_direction_budget == 0
    assert effective.conversation_strategies == ("ask_for_detail",)


def test_low_initiative_is_weight_not_absolute_speaking_ban() -> None:
    effective, decision = apply_conversation_response_policy(
        _autonomy_plan(),
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.20,
        user_input="この後はどうするの",
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
    assert effective.conversation_strategies == (
        "take_initiative",
        "state_choice",
        "define_next_step",
    )


def test_user_question_selects_direct_answer_mode() -> None:
    effective, decision = apply_conversation_response_policy(
        _expansive_plan(),
        speech_act="question",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="今日はゲームする？",
        drive={"curiosity": 0.9},
    )

    assert decision.mode is ConversationResponseMode.ANSWER
    assert effective.question_budget == 0
    assert effective.new_direction_budget == 0
    assert effective.self_disclosure_level == "none"
    assert effective.conversation_strategies == ("explain_clearly",)


def test_decision_context_exposes_scores_and_reasons() -> None:
    decision = decide_conversation_response_mode(
        _expansive_plan(),
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.65,
        user_input="いいね。そういうの",
        drive={"curiosity": 0.5},
    )

    context = decision.as_context()
    assert context["mode"] == "listen"
    assert context["low_information_input"] is True
    assert isinstance(context["scores"], dict)
    assert context["reasons"]


def test_character_prompt_projects_state_driven_reaction_decision() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(
            initiative_level=0.15,
            phase="greeting",
            speech_act="greeting",
            drive={"curiosity": 0.5, "engagement": 0.5, "energy": 0.7},
        ),
        character_profile=None,
        correction=None,
    )

    assert '"mode": "react"' in prompt
    assert '"question_budget": 0' in prompt
    assert '"new_direction_budget": 0' in prompt
    assert "今回のConversation Response Modeはreact" in prompt
    assert "入力種別だけによる一律の質問禁止・話題禁止ではない" in prompt
    assert "この応答は低主体性の挨拶である" not in prompt


def test_character_prompt_allows_state_selected_question_after_acknowledgement() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(
            initiative_level=0.65,
            phase="active",
            speech_act="statement",
            user_input="いいね。そういうの",
            drive={
                "curiosity": 0.99,
                "engagement": 0.8,
                "energy": 0.8,
            },
        ),
        character_profile=None,
        correction=None,
    )

    assert '"mode": "ask"' in prompt
    assert '"question_budget": 1' in prompt
    assert "現在の好奇心や関心に結び付く" in prompt
    assert "入力分類ではなく、上記で選ばれたResponse Modeに従う" in prompt
    assert "質問、新話題、自己開示を追加しない" not in prompt


def test_validator_uses_same_effective_decision_as_character_prompt() -> None:
    context = _context(
        initiative_level=0.65,
        phase="active",
        speech_act="statement",
        user_input="いいね。そういうの",
        drive={
            "curiosity": 0.99,
            "engagement": 0.8,
            "energy": 0.8,
        },
    )
    prompt = ResponseValidatorPromptBuilder().build(
        context,
        CharacterResponse(speech="それなら、どんなところが一番好き？"),
    )

    assert '"mode": "ask"' in prompt
    assert "Effective Response Content Plan" in prompt
    assert '"question_budget": 1' in prompt
    assert "入力が挨拶・相槌であることだけを理由に質問や発話を拒否しない" in prompt
