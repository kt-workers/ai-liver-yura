from __future__ import annotations

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


def _directive() -> InternalDirective:
    return InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal="現在の気分について直接回答する",
        activity_intent=None,
        initiative_level=0.1,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.2,
        content_requirements=("現在の気分に答える",),
        forbidden_claims=(),
    )


def test_prompt_keeps_current_feeling_state_as_hidden_generation_context() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _meaning(),
        _planning_input(),
        character_profile=_profile(),
    )

    assert "internal_stateまたはagent_internal_state" in prompt
    assert "current_feeling" in prompt
    assert "internal_state.emotionやinternal_state.driveはPlanner判断の根拠" in prompt
    assert "発話すべき内容として移してはいけない" in prompt
    assert "内部状態はCharacter表現を生む原因" in prompt
    assert "固定文、固定フレーズ、状態名ごとの言い換え辞書" in prompt
    assert "drive.curiosityは好奇心・関心" in prompt
    assert "self_disclosure_levelは0.35以上" in prompt
    assert '"calm": 0.74' in prompt
    assert '"joy": 0.58' in prompt
    assert '"curiosity": 0.61' in prompt
    assert "数値が高い1〜2項目をresponse_goalへ具体的に含め" not in prompt
    assert "根拠の項目名と数値を明記" not in prompt
    assert "0.70以上を強め" not in prompt


@pytest.mark.parametrize(
    "target_type",
    ("internal_state", "agent_internal_state"),
)
@pytest.mark.parametrize(
    "target_id",
    ("current_feeling", "current_mood", "current_emotion", "mood", "feeling"),
)
def test_validator_removes_diagnostic_current_feeling_guidance_for_aliases(
    target_type: str,
    target_id: str,
) -> None:
    diagnostic_directive = InternalDirective(
        response_mode=ResponseMode.ASK,
        response_goal="現在の気分は中立的で落ち着いています。",
        activity_intent=None,
        initiative_level=0.8,
        question_budget=2,
        new_direction_budget=2,
        self_disclosure_level=0.2,
        content_requirements=(
            "質問へ自然に直接答える",
            "落ち着いて、短く答える",
            "落ち着きが強め",
            "中立的な気分",
            "Emotion evidence: calm=0.74",
            "Drive evidence: curiosity=0.61",
        ),
        forbidden_claims=(),
    )
    validated = InternalDirectiveValidator().validate(
        _meaning(target_type, target_id),
        diagnostic_directive,
        _planning_input(),
        character_profile=_profile(),
    )

    requirements = "\n".join(validated.directive.content_requirements)
    forbidden = "\n".join(validated.directive.forbidden_claims)

    assert validated.directive.response_mode is ResponseMode.ANSWER
    assert validated.directive.question_budget == 0
    assert validated.directive.new_direction_budget == 0
    assert validated.directive.self_disclosure_level == 0.35
    assert validated.directive.response_goal == (
        "現在の内的状態に沿って、ユーザーの質問へ自然に直接答える"
    )
    assert "internal_state_question_allows_direct_disclosure" in (
        validated.validation_notes
    )
    assert "current_feeling_guidance_normalized" in validated.validation_notes
    assert "質問へ自然に直接答える" in requirements
    assert "落ち着いて、短く答える" in requirements
    assert "落ち着きが強め" not in requirements
    assert "中立的な気分" not in requirements
    assert "Emotion evidence" not in requirements
    assert "Drive evidence" not in requirements
    assert "calm" not in requirements
    assert "curiosity" not in requirements
    assert "0.74" not in requirements
    assert "0.61" not in requirements
    assert "内部キー名、数値、強度分類" in forbidden
    assert "neutralや中立などの内部分類" in forbidden
    assert "物理的な身体を持たないため" not in requirements


def test_individual_joy_question_uses_motivation_engagement() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_current_joy",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("internal_state", "joy"),
        confidence=0.98,
    )

    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(),
        _planning_input(),
        character_profile=_profile(),
    )

    requirements = "\n".join(validated.directive.content_requirements)
    assert "joy=0.58" in requirements
    assert "amusement=0.22" in requirements
    assert "engagement=0.57" in requirements


@pytest.mark.parametrize(
    ("target_id", "expected_requirement"),
    (
        ("anger", "現在のanger=0.0を根拠に率直に回答する"),
        ("current_desire", "Drive evidence:"),
    ),
)
def test_individual_internal_state_questions_keep_existing_guidance(
    target_id: str,
    expected_requirement: str,
) -> None:
    validated = InternalDirectiveValidator().validate(
        _meaning(target_id=target_id),
        _directive(),
        _planning_input(),
        character_profile=_profile(),
    )

    requirements = "\n".join(validated.directive.content_requirements)
    assert expected_requirement in requirements
    assert "内部キー名と数値は発話で読み上げず" in requirements
