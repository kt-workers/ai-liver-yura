from __future__ import annotations

from app.domain.cognitive_direction import (
    ActivityIntent,
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
    mode: ResponseMode = ResponseMode.LISTEN,
    activity_intent: ActivityIntent | None = None,
    question_budget: int = 0,
    new_direction_budget: int = 0,
) -> InternalDirective:
    return InternalDirective(
        response_mode=mode,
        response_goal="候補の応答方針",
        activity_intent=activity_intent,
        initiative_level=0.8,
        question_budget=question_budget,
        new_direction_budget=new_direction_budget,
        self_disclosure_level=0.1,
        content_requirements=(),
        forbidden_claims=(),
    )


def _meaning(
    *,
    speech_act: InputSpeechAct,
    intent: str,
    expected_response: ExpectedResponse,
    target: InputTarget | None = None,
) -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=speech_act,
        primary_intent=intent,
        expected_response=expected_response,
        target=target,
        confidence=0.98,
    )


def _planning_input() -> dict[str, object]:
    return {
        "emotion": {"joy": 0.84, "calm": 0.58, "amusement": 0.46},
        "drive": {"curiosity": 0.94, "social": 0.76},
        "relationship": {"familiarity": 0.64, "trust": 0.74},
        "motivation": {"engagement": 0.81},
        "moral": {"care": 0.82, "honesty": 0.92},
        "situation": {"current_topic": "深海の未知の生物"},
        "memory": {},
        "related_knowledge": [],
        "last_activity_result": None,
        "ongoing_activity": None,
        "available_activities": [],
    }


def test_prompt_covers_multi_preset_decision_rules() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _meaning(
            speech_act=InputSpeechAct.STATEMENT,
            intent="share_positive_experience",
            expected_response=ExpectedResponse.ACKNOWLEDGEMENT,
            target=InputTarget("user_experience", "positive_event"),
        ),
        _planning_input(),
        character_profile=_profile(),
    )

    assert "operation=continue" in prompt
    assert "supported_operationsまたはoperations" in prompt
    assert "高いjoy、care、social、engagement" in prompt
    assert "closingではresponse_mode=react" in prompt
    assert "既存knowledge_gaps" in prompt
    assert "question_budget=1" in prompt
    assert "内部表現を読まない" in prompt
    assert "機械的に毎回列挙しない" in prompt


def test_validator_restores_explicit_ongoing_activity_continuation() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.REQUEST,
        intent="continue_previous_explanation",
        expected_response=ExpectedResponse.ACTION,
        target=InputTarget("activity", "directive_explanation"),
    )
    planning_input = _planning_input()
    planning_input["ongoing_activity"] = {
        "activity_type": "conversation",
        "goal": "内部指示器の設計を順序立てて説明する",
        "status": "waiting",
    }
    planning_input["available_activities"] = [
        {
            "activity_type": "conversation",
            "operations": ["continue", "explain", "discuss"],
        }
    ]

    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(mode=ResponseMode.ANSWER),
        planning_input,
        character_profile=_profile(),
    )

    intent = validated.directive.activity_intent
    assert intent is not None
    assert intent.activity_type == "conversation"
    assert intent.operation == "continue"
    assert intent.constraints["maintain_current_goal"] is True
    assert "explicit_ongoing_activity_continuation_restored" in (
        validated.validation_notes
    )


def test_validator_accepts_operations_alias_for_activity_registry() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.REQUEST,
        intent="continue_previous_explanation",
        expected_response=ExpectedResponse.ACTION,
        target=InputTarget("activity", "directive_explanation"),
    )
    planning_input = _planning_input()
    planning_input["available_activities"] = [
        {
            "activity_type": "conversation",
            "operations": ["continue"],
        }
    ]
    requested = ActivityIntent(
        activity_type="conversation",
        operation="continue",
        constraints={},
    )

    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(activity_intent=requested),
        planning_input,
        character_profile=_profile(),
    )

    assert validated.directive.activity_intent == requested
    assert "activity_intent_rejected_by_registry" not in validated.validation_notes


def test_positive_experience_forces_empathic_reaction() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.STATEMENT,
        intent="share_positive_experience",
        expected_response=ExpectedResponse.ACKNOWLEDGEMENT,
        target=InputTarget("user_experience", "positive_event"),
    )

    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(mode=ResponseMode.LISTEN),
        _planning_input(),
        character_profile=_profile(),
    )

    requirements = "\n".join(validated.directive.content_requirements)
    forbidden = "\n".join(validated.directive.forbidden_claims)
    assert validated.directive.response_mode is ResponseMode.REACT
    assert validated.directive.question_budget == 0
    assert validated.directive.new_direction_budget == 0
    assert "短く一緒に喜び" in requirements
    assert "joy=0.84" in requirements
    assert "care=0.82" in requirements
    assert "内部状態のキー名や数値は発話で読み上げず" in requirements
    assert "単なる受領だけで終える" in forbidden
    assert "物理的な身体を持たないため" not in requirements


def test_existing_target_gap_authorizes_one_related_question() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.STATEMENT,
        intent="share_interesting_topic",
        expected_response=ExpectedResponse.ACKNOWLEDGEMENT,
        target=InputTarget("topic", "deep_sea_unknown_life"),
    )
    planning_input = _planning_input()
    planning_input["related_knowledge"] = [
        {
            "target_type": "topic",
            "target_id": "deep_sea_unknown_life",
            "interest": 0.94,
            "knowledge_gaps": [
                "未発見生物が多いと考えられている深度や環境"
            ],
        }
    ]

    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(
            mode=ResponseMode.ASK,
            question_budget=0,
            new_direction_budget=1,
        ),
        planning_input,
        character_profile=_profile(),
    )

    assert validated.directive.response_mode is ResponseMode.ASK
    assert validated.directive.question_budget == 1
    assert validated.directive.new_direction_budget == 0
    assert "existing_target_gap_authorizes_single_question" in (
        validated.validation_notes
    )


def test_global_curiosity_without_target_gap_cannot_authorize_question() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.STATEMENT,
        intent="share_interesting_topic",
        expected_response=ExpectedResponse.ACKNOWLEDGEMENT,
        target=InputTarget("topic", "deep_sea_unknown_life"),
    )

    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(
            mode=ResponseMode.ASK,
            question_budget=1,
            new_direction_budget=1,
        ),
        _planning_input(),
        character_profile=_profile(),
    )

    assert validated.directive.response_mode is ResponseMode.LISTEN
    assert validated.directive.question_budget == 0
    assert validated.directive.new_direction_budget == 0
    assert "global_curiosity_does_not_authorize_question" in (
        validated.validation_notes
    )


def test_closing_forces_brief_reaction() -> None:
    meaning = _meaning(
        speech_act=InputSpeechAct.CLOSING,
        intent="end_conversation",
        expected_response=ExpectedResponse.NO_RESPONSE,
    )

    validated = InternalDirectiveValidator().validate(
        meaning,
        _directive(mode=ResponseMode.LISTEN),
        _planning_input(),
        character_profile=_profile(),
    )

    requirements = "\n".join(validated.directive.content_requirements)
    assert validated.directive.response_mode is ResponseMode.REACT
    assert validated.directive.question_budget == 0
    assert validated.directive.new_direction_budget == 0
    assert "短い別れの挨拶を1文" in requirements
