from __future__ import annotations

import json

import pytest

from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.prompting.cognitive_direction_prompt_builders import (
    InternalDirectivePromptBuilder,
)
from app.runtime.cognitive_direction_parsers import InputMeaningJsonParser
from app.runtime.internal_directive_validator import InternalDirectiveValidator


def _meaning(
    target_type: str = "internal_state",
    target_id: str = "current_feeling",
) -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_current_feeling",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget(target_type, target_id),
        confidence=0.98,
    )


def _planning_input() -> dict[str, object]:
    return {
        "emotion": {
            "joy": 0.58,
            "calm": 0.74,
            "amusement": 0.22,
        },
        "drive": {
            "curiosity": 0.61,
            "social": 0.55,
        },
        "relationship": {
            "familiarity": 0.45,
            "trust": 0.62,
        },
        "motivation": {"engagement": 0.57},
        "moral": {"care": 0.8, "honesty": 0.9},
        "situation": {"current_topic": "現在の気分"},
        "memory": {},
        "related_knowledge": [],
        "last_activity_result": None,
        "ongoing_activity": None,
        "available_activities": [],
    }


def _profile() -> dict[str, object]:
    return {
        "name": "ゆら",
        "existence": {
            "physical_capabilities": ["物理的な身体を持たない"],
            "experience_boundaries": [
                "根拠のない現実空間での実体験を語らない"
            ],
        },
    }


def _directive(
    *,
    response_goal: str = "現在の気分について直接回答する",
    content_requirements: tuple[str, ...] = ("現在の気分に答える",),
    forbidden_claims: tuple[str, ...] = (),
) -> InternalDirective:
    return InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal=response_goal,
        activity_intent=None,
        initiative_level=0.1,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.2,
        content_requirements=content_requirements,
        forbidden_claims=forbidden_claims,
    )


def test_prompt_applies_hidden_state_boundary_to_all_internal_state_targets() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _meaning(target_id="current_concern"),
        _planning_input(),
        character_profile=_profile(),
    )

    assert "internal_stateまたはagent_internal_state" in prompt
    assert "target.idごとの例外を作らず" in prompt
    assert "すべての内部状態targetへ" in prompt
    assert "自然語へ変換した診断内容" in prompt
    assert "response_goal、content_requirements、forbidden_claims" in prompt
    assert "content_requirementsへ状態説明を生成しない" in prompt
    assert "cause/evidence" in prompt
    assert "固定文、固定フレーズ、状態名ごとの言い換え辞書" in prompt
    assert "self_disclosure_levelは0.35以上" in prompt
    assert '"calm": 0.74' in prompt
    assert '"joy": 0.58' in prompt
    assert '"curiosity": 0.61' in prompt
    assert "target.idがcurrent_feeling" not in prompt


def test_naturalized_diagnostic_guidance_is_structurally_discarded() -> None:
    diagnostic_directive = _directive(
        response_goal=(
            "現在はほどよく落ち着いていて"
            "少しワクワクしていることを伝える"
        ),
        content_requirements=(
            "ほどよく落ち着いていることを伝える",
            "少しワクワクしていることを伝える",
        ),
        forbidden_claims=("沈んでいるようには言わない",),
    )

    validated = InternalDirectiveValidator().validate(
        _meaning(),
        diagnostic_directive,
        _planning_input(),
        character_profile=_profile(),
    )

    assert validated.directive.response_goal == (
        "ユーザーが尋ねた内的状態について、現在の状態に沿って自然に直接答える"
    )
    assert validated.directive.content_requirements == ()
    forbidden = "\n".join(validated.directive.forbidden_claims)
    assert "ほどよく落ち着いて" not in forbidden
    assert "ワクワク" not in forbidden
    assert "沈んでいる" not in forbidden
    assert "internal_state_guidance_normalized" in validated.validation_notes


@pytest.mark.parametrize("target_type", ("internal_state", "agent_internal_state"))
@pytest.mark.parametrize(
    "target_id",
    (
        "current_feeling",
        "joy",
        "anger",
        "current_desire",
        "current_concern",
        "loneliness",
        "confidence",
    ),
)
def test_direct_internal_state_questions_share_one_structural_boundary(
    target_type: str,
    target_id: str,
) -> None:
    diagnostic_directive = InternalDirective(
        response_mode=ResponseMode.ASK,
        response_goal="Plannerが作った具体的な状態説明",
        activity_intent=None,
        initiative_level=0.8,
        question_budget=2,
        new_direction_budget=2,
        self_disclosure_level=0.2,
        content_requirements=(
            "Planner由来の状態説明要件",
        ),
        forbidden_claims=("Planner由来の状態説明禁止",),
    )
    validated = InternalDirectiveValidator().validate(
        _meaning(target_type, target_id),
        diagnostic_directive,
        _planning_input(),
        character_profile=_profile(),
    )

    forbidden = "\n".join(validated.directive.forbidden_claims)

    assert validated.meaning.target == InputTarget(target_type, target_id)
    assert validated.directive.response_mode is ResponseMode.ANSWER
    assert validated.directive.question_budget == 0
    assert validated.directive.new_direction_budget == 0
    assert validated.directive.self_disclosure_level == 0.35
    assert validated.directive.response_goal == (
        "ユーザーが尋ねた内的状態について、現在の状態に沿って自然に直接答える"
    )
    assert validated.directive.content_requirements == ()
    assert "internal_state_question_allows_direct_disclosure" in validated.validation_notes
    assert "internal_state_guidance_normalized" in validated.validation_notes
    assert "Planner由来" not in forbidden
    assert "内部キー名、数値、強度分類" in forbidden
    assert "engagementやcuriosity" in forbidden


@pytest.mark.parametrize(
    ("target_id", "bad_goal", "bad_requirements"),
    (
        (
            "joy",
            "joyが低いので現在はあまり楽しくないと伝える",
            ("joy=0.0", "amusement=0.0", "今は喜びを感じていないことを伝える"),
        ),
        (
            "anger",
            "angerが低いので怒っていないと伝える",
            ("anger=0.0", "怒っていないことを明示する"),
        ),
        (
            "current_desire",
            "好奇心が高いので新しいことをしたいと伝える",
            ("Drive evidence: curiosity=0.61", "新しいことをしたいと伝える"),
        ),
    ),
)
def test_individual_internal_state_planner_evidence_is_not_forwarded(
    target_id: str,
    bad_goal: str,
    bad_requirements: tuple[str, ...],
) -> None:
    validated = InternalDirectiveValidator().validate(
        _meaning(target_id=target_id),
        _directive(
            response_goal=bad_goal,
            content_requirements=bad_requirements,
        ),
        _planning_input(),
        character_profile=_profile(),
    )

    assert validated.directive.content_requirements == ()
    assert validated.directive.response_goal != bad_goal
    serialized = "\n".join(
        (
            validated.directive.response_goal,
            *validated.directive.content_requirements,
        )
    )
    assert all(requirement not in serialized for requirement in bad_requirements)


def test_parsed_current_concern_target_uses_generic_internal_state_boundary() -> None:
    raw = {
        "input_speech_act": "question",
        "primary_intent": "ask_current_concern",
        "expected_response": "direct_answer",
        "target": {"type": "internal_state", "id": "current_concern"},
        "entities": [],
        "references": [],
        "information_provided": [],
        "negated": False,
        "hypothetical": False,
        "past_reference": False,
        "conversation_phase_signal": "continue",
        "confidence": 0.98,
        "reason": "semantic target classified",
    }
    meaning = InputMeaningJsonParser().parse(
        json.dumps(raw),
        source_text="input",
    )

    assert meaning is not None
    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(
            response_goal="何も気になっていないと伝える",
            content_requirements=("心配はないと明示する",),
        ),
        _planning_input(),
        character_profile=_profile(),
    )

    assert validated.meaning.target == InputTarget(
        "internal_state",
        "current_concern",
    )
    assert validated.directive.content_requirements == ()
    assert "internal_state_guidance_normalized" in validated.validation_notes


def test_non_internal_state_question_keeps_planner_guidance() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_knowledge",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("topic", "ocean"),
        confidence=0.98,
    )
    directive = _directive(
        response_goal="海について説明する",
        content_requirements=("深海の特徴を簡潔に説明する",),
        forbidden_claims=("未確認の深度を断定しない",),
    )

    validated = InternalDirectiveValidator().validate(
        meaning,
        directive,
        _planning_input(),
        character_profile=_profile(),
    )

    assert validated.directive.response_goal == directive.response_goal
    assert validated.directive.content_requirements == directive.content_requirements
    assert validated.directive.forbidden_claims == directive.forbidden_claims
    assert "internal_state_guidance_normalized" not in validated.validation_notes


def test_existence_constraints_are_added_after_internal_state_guidance_reset() -> None:
    meaning = _meaning(target_id="physical_hunger")
    directive = _directive(
        response_goal="今は空腹ではないと伝える",
        content_requirements=("空腹度は0.0だと説明する",),
        forbidden_claims=("満腹だとは言わない",),
    )

    validated = InternalDirectiveValidator().validate(
        meaning,
        directive,
        _planning_input(),
        character_profile=_profile(),
    )

    requirements = "\n".join(validated.directive.content_requirements)
    forbidden = "\n".join(validated.directive.forbidden_claims)
    assert "空腹度は0.0" not in requirements
    assert "満腹だとは言わない" not in forbidden
    assert "物理的身体感覚は持たない" in requirements
    assert "今は空腹でないだけ" in forbidden
    assert "internal_state_guidance_normalized" in validated.validation_notes
