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


def _meaning(target_type: str = "internal_state") -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_current_feeling",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget(target_type, "current_feeling"),
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


def test_prompt_requires_concrete_current_feeling_evidence() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _meaning(),
        _planning_input(),
        character_profile=_profile(),
    )

    assert "internal_stateまたはagent_internal_state" in prompt
    assert "current_feeling" in prompt
    assert "数値が高い1〜2項目をresponse_goalへ具体的に含め" in prompt
    assert "根拠の項目名と数値を明記" in prompt
    assert "抽象方針だけで終えてはいけない" in prompt
    assert "0.70以上を強め" in prompt
    assert "0.45以上0.70未満を中程度" in prompt
    assert "drive.curiosityは好奇心・関心" in prompt
    assert "self_disclosure_levelは0.35以上" in prompt
    assert '"calm": 0.74' in prompt
    assert '"joy": 0.58' in prompt
    assert '"curiosity": 0.61' in prompt


@pytest.mark.parametrize(
    "target_type",
    ("internal_state", "agent_internal_state"),
)
def test_validator_adds_current_feeling_evidence_for_target_aliases(
    target_type: str,
) -> None:
    validated = InternalDirectiveValidator().validate(
        _meaning(target_type),
        _directive(),
        _planning_input(),
        character_profile=_profile(),
    )

    requirements = "\n".join(validated.directive.content_requirements)
    forbidden = "\n".join(validated.directive.forbidden_claims)

    assert validated.directive.self_disclosure_level == 0.35
    assert "internal_state_question_allows_direct_disclosure" in (
        validated.validation_notes
    )
    assert "現在の気分の中心候補: calm=0.74 (強め), joy=0.58 (中程度)" in (
        requirements
    )
    assert '"amusement": 0.22' in requirements
    assert '"calm": 0.74' in requirements
    assert '"joy": 0.58' in requirements
    assert "curiosity=0.61" in requirements
    assert "低いEmotion値を主感情として強く誇張する" in forbidden
    assert "curiosityやengagementだけを根拠に" in forbidden
    assert "現在値にない悲しみ、怒り、強い興奮" in forbidden
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
