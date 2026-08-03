from __future__ import annotations

from app.domain.cognitive_direction import (
    ActivityIntent,
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InterestChange,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
    TargetInterestUpdate,
)
from app.prompting.cognitive_direction_prompt_builders import (
    InputMeaningPromptBuilder,
    InternalDirectivePromptBuilder,
)
from app.runtime.internal_directive_validator import InternalDirectiveValidator


def _profile_without_physical_body() -> dict[str, object]:
    return {
        "name": "ゆら",
        "existence": {
            "physical_capabilities": ["物理的な身体を持たない"],
            "sensory_capabilities": ["入力として渡された情報だけを知覚する"],
            "experience_boundaries": [
                "根拠のない現実空間での実体験を語らない"
            ],
            "world_relationship": "デジタル空間からユーザーと会話する存在",
        },
    }


def _planning_input() -> dict[str, object]:
    return {
        "emotion": {"joy": 0.31, "calm": 0.73, "amusement": 0.17},
        "drive": {"curiosity": 0.28, "social": 0.48},
        "relationship": {"familiarity": 0.57, "trust": 0.69},
        "motivation": {"engagement": 0.51},
        "moral": {"care": 0.82, "honesty": 0.98},
        "situation": {"current_topic": "ゆらの昨日の外出経験"},
        "memory": {},
        "related_knowledge": [],
        "last_activity_result": None,
        "ongoing_activity": None,
        "available_activities": [
            {
                "activity_type": "conversation",
                "supported_operations": ["explain", "discuss"],
            }
        ],
    }


def _physical_experience_meaning() -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_physical_experience",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("character_experience", "yesterday_outing"),
        past_reference=True,
        confidence=0.98,
        reason="昨日の現実世界での外出経験を尋ねている",
    )


def test_input_meaning_prompt_marks_explicit_past_reference() -> None:
    prompt = InputMeaningPromptBuilder().build(
        {
            "event": {
                "type": "user_text",
                "user_text": "昨日はどこかへ出かけた？",
            }
        }
    )

    assert "明確な過去時点" in prompt
    assert "past_reference=true" in prompt
    assert "経験が可能かどうかはこの役割では判断しない" in prompt


def test_internal_directive_prompt_distinguishes_impossible_from_unknown() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _physical_experience_meaning(),
        _planning_input(),
        character_profile=_profile_without_physical_body(),
    )

    assert "activity_intent=null" in prompt
    assert "conversationがあるだけを理由" in prompt
    assert "単なる未確認・不明として扱わず" in prompt
    assert "不可能な経験の有無や内容をnew_knowledge_gapsへ追加してはいけない" in prompt


def test_validator_rejects_activity_and_knowledge_gap_for_impossible_experience() -> None:
    directive = InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal="昨日の外出経験について答える",
        activity_intent=ActivityIntent(
            activity_type="conversation",
            operation="explain",
        ),
        initiative_level=0.08,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.0,
        content_requirements=("必要なら未確認であることを示す",),
        target_interest_updates=(
            TargetInterestUpdate(
                target_type="character_experience",
                target_id="yesterday_outing",
                interest_change=InterestChange.UNCHANGED,
                new_knowledge_gaps=(
                    "昨日の外出経験の有無",
                    "外出内容の具体",
                ),
            ),
        ),
    )

    plan = InternalDirectiveValidator().validate(
        _physical_experience_meaning(),
        directive,
        _planning_input(),
        character_profile=_profile_without_physical_body(),
    )

    assert plan.directive.activity_intent is None
    assert plan.directive.target_interest_updates == ()
    assert "direct_question_rejects_activity_intent" in plan.validation_notes
    assert (
        "impossible_embodied_experience_rejects_knowledge_gaps"
        in plan.validation_notes
    )
    requirements = "\n".join(plan.directive.content_requirements)
    forbidden = "\n".join(plan.directive.forbidden_claims)
    assert "物理的な身体を持たないため" in requirements
    assert "未確認・不明という曖昧な説明ではなく" in requirements
    assert "単に未確認または情報不足" in forbidden
    assert "経験の内容を創作" in forbidden


def test_validator_preserves_reachable_nonphysical_knowledge_gap() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.STATEMENT,
        primary_intent="share_interesting_topic",
        expected_response=ExpectedResponse.ACKNOWLEDGEMENT,
        target=InputTarget("topic", "deep_sea_unknown_life"),
        confidence=0.96,
    )
    update = TargetInterestUpdate(
        target_type="topic",
        target_id="deep_sea_unknown_life",
        interest_change=InterestChange.SLIGHTLY_INCREASE,
        new_knowledge_gaps=("未分類生物の特徴",),
    )
    directive = InternalDirective(
        response_mode=ResponseMode.ASK,
        response_goal="深海生物について関心を示す",
        activity_intent=None,
        initiative_level=0.6,
        question_budget=1,
        new_direction_budget=1,
        self_disclosure_level=0.0,
        target_interest_updates=(update,),
    )

    plan = InternalDirectiveValidator().validate(
        meaning,
        directive,
        _planning_input(),
        character_profile=_profile_without_physical_body(),
    )

    assert plan.directive.target_interest_updates == (update,)
    assert plan.directive.response_mode is ResponseMode.ASK
    assert (
        "impossible_embodied_experience_rejects_knowledge_gaps"
        not in plan.validation_notes
    )
