from __future__ import annotations

from app.adapters.prompt.character_prompt_builder import CharacterPromptBuilder
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.conversation_utterance_policy import (
    constrain_response_content_plan,
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


def _context(*, initiative_level: float, phase: str, speech_act: str) -> ResponseContext:
    return ResponseContext(
        user_input="こんにちは",
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
        memory={"response_content_plan": _expansive_plan().as_context()},
    )


def test_low_initiative_greeting_removes_questions_new_topics_and_self_disclosure() -> None:
    constrained = constrain_response_content_plan(
        _expansive_plan(),
        speech_act="greeting",
        conversation_phase="greeting",
        initiative_level=0.15,
    )

    assert constrained.question_budget == 0
    assert constrained.new_direction_budget == 0
    assert constrained.self_disclosure_level == "none"
    assert constrained.conversation_strategies == ("acknowledge_other",)
    assert "low_initiative_greeting_constrained" in constrained.reasons


def test_active_response_preserves_original_content_plan() -> None:
    original = _expansive_plan()

    constrained = constrain_response_content_plan(
        original,
        speech_act="question",
        conversation_phase="active",
        initiative_level=0.65,
    )

    assert constrained == original


def test_low_initiative_non_greeting_removes_expansion_strategies() -> None:
    constrained = constrain_response_content_plan(
        _expansive_plan(),
        speech_act="statement",
        conversation_phase="active",
        initiative_level=0.20,
    )

    assert constrained.question_budget == 0
    assert constrained.new_direction_budget == 0
    assert constrained.conversation_strategies == ("self_disclose_briefly",)
    assert "low_initiative_response_constrained" in constrained.reasons


def test_character_prompt_projects_effective_greeting_plan_and_explicit_limit() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(
            initiative_level=0.15,
            phase="greeting",
            speech_act="greeting",
        ),
        character_profile=None,
        correction=None,
    )

    assert '"question_budget": 0' in prompt
    assert '"new_direction_budget": 0' in prompt
    assert '"self_disclosure_level": "none"' in prompt
    assert '"conversation_strategies": ["acknowledge_other"]' in prompt
    assert "この応答は低主体性の挨拶である" in prompt
    assert "質問、自己開示、新しい話題" in prompt
    assert "最近の関心や好みの持ち出し" in prompt
    assert "observation_onlyはActivity選択へ介入しない安全属性" in prompt


def test_character_prompt_keeps_active_conversation_budgets() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(
            initiative_level=0.65,
            phase="active",
            speech_act="question",
        ),
        character_profile=None,
        correction=None,
    )

    assert '"question_budget": 1' in prompt
    assert '"new_direction_budget": 1' in prompt
    assert '"self_disclosure_level": "brief"' in prompt
    assert "この応答は低主体性の挨拶である" not in prompt
