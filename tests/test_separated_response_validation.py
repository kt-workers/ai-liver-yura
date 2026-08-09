from __future__ import annotations

import json

import pytest

from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.character_utterance import LinguisticPerformance
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.character_realization_validator import CharacterRealizationValidator
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner
from app.runtime.semantic_utterance_validator import SemanticUtteranceValidator


class _RecordingValidationModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.response


def _envelope(target_id: str = "joy") -> dict[str, object]:
    return {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": target_id},
        },
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "現在の内部状態へ自然に直接答える",
            "question_budget": 0,
            "new_direction_budget": 0,
            "self_disclosure_level": 0.35,
            "content_requirements": [],
            "forbidden_claims": [],
        },
        "existence_boundaries": [
            "存在種別はAI VTuberである",
            "見た・行った・触った等の実体験は根拠がある場合だけ語る",
        ],
    }


def _base_context() -> ResponseContext:
    return ResponseContext(
        user_input="楽しい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の内部状態へ直接答える",
        speech_act="question",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.0,
                    "amusement": 0.0,
                    "calm": 0.58,
                }
            }
        },
        drive={"curiosity": 0.82, "engagement": 0.78},
        constraints={"_internal_directive": _envelope()},
    )


def _validated_context() -> ResponseContext:
    context = _base_context()
    plan = ResponseSemanticsPlanner().plan(context)
    return ResponseContext(
        user_input=context.user_input,
        activity_type=context.activity_type,
        operation=context.operation,
        status=context.status,
        failure_reason=context.failure_reason,
        result_summary=context.result_summary,
        allowed_claims=context.allowed_claims,
        forbidden_claims=context.forbidden_claims,
        activity_goal=context.activity_goal,
        speech_act=context.speech_act,
        emotion=context.emotion,
        drive=context.drive,
        constraints=context.constraints,
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )


def _response(
    speech: str = "今は、そこまで楽しいって感じじゃないかな。",
    *,
    realizations: tuple[str, ...] = ("proposition:0:joy",),
) -> CharacterResponse:
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(
            phrasing=(speech,),
            delivery_tags=("gentle",),
        ),
        semantic_realizations=realizations,
    )


def test_semantic_validator_accepts_canonical_plan() -> None:
    context = _base_context()
    plan = ResponseSemanticsPlanner().plan(context)

    result = SemanticUtteranceValidator().validate(context, plan)

    assert result.accepted is True
    assert result.reason == "semantic_plan_consistent"
    assert result.differences == ()


def test_semantic_validator_rejects_modified_target_proposition() -> None:
    context = _base_context()
    canonical = ResponseSemanticsPlanner().plan(context)
    value = canonical.as_context()
    propositions = list(value["propositions"])
    assert isinstance(propositions[0], dict)
    propositions[0] = dict(propositions[0])
    propositions[0]["state"] = "present"
    value["propositions"] = propositions
    modified = SemanticUtterancePlan.from_context(value)

    assert modified is not None
    result = SemanticUtteranceValidator().validate(context, modified)

    assert result.accepted is False
    assert result.reason == "semantic_plan_inconsistent_with_structured_facts"
    assert "proposition_mismatch" in result.differences


def test_realization_validator_prompt_uses_semantic_plan_not_raw_internal_state() -> None:
    context = _validated_context()
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        context,
        _response(),
    )

    assert "# Semantic Utterance Plan" in prompt
    assert '"predicate": "joy"' in prompt
    assert '"state": "absent"' in prompt
    assert "emotion.current.reactive.joy" not in prompt
    assert "evidence_refs" not in prompt
    assert "0.82" not in prompt
    assert "0.58" not in prompt
    assert "# User Wording Hint" in prompt
    assert '"utterance": "楽しい？"' in prompt
    assert "意味の近い別概念へ置換していない" in prompt
    assert "事実の正本ではない" in prompt


@pytest.mark.asyncio
async def test_realization_validator_model_invocation_is_sanitized() -> None:
    model = _RecordingValidationModel(
        json.dumps(
            {
                "accepted": True,
                "reason": "semantic_realization_consistent",
                "differences": [],
            },
            ensure_ascii=False,
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="test-event",
    )

    result = await validator.validate(source, _validated_context(), _response())

    assert result.accepted is True
    assert result.reason == "semantic_realization_consistent"
    assert len(model.activities) == 1
    activity = model.activities[0]
    assert activity.context["llm_role"] == "character_realization_validator"
    assert activity.context["semantic_boundary"] is True
    for forbidden_key in (
        "response_context",
        "character_response",
        "user_input",
        "event_payload",
        "activity_execution_result",
        "ongoing_activity",
    ):
        assert forbidden_key not in activity.context
    prompt = str(activity.context["plugin_prompt_override"])
    assert "0.82" not in prompt
    assert "0.58" not in prompt
    assert "emotion.current.reactive.joy" not in prompt
    assert '"utterance": "楽しい？"' in prompt


@pytest.mark.asyncio
async def test_missing_primary_semantic_realization_is_rejected_before_model_call() -> None:
    model = _RecordingValidationModel(
        json.dumps({"accepted": True, "reason": "should_not_run", "differences": []})
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
    )

    result = await validator.validate(
        source,
        _validated_context(),
        _response(realizations=()),
    )

    assert result.accepted is False
    assert result.reason == "required_semantic_realization_missing"
    assert model.activities == []


@pytest.mark.asyncio
async def test_model_rejection_is_returned_as_realization_difference() -> None:
    model = _RecordingValidationModel(
        json.dumps(
            {
                "accepted": False,
                "reason": "target_polarity_changed",
                "differences": ["joy_absent_became_positive"],
            },
            ensure_ascii=False,
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
    )

    result = await validator.validate(
        source,
        _validated_context(),
        _response(speech="うん、少し楽しいよ。"),
    )

    assert result.accepted is False
    assert result.reason == "target_polarity_changed"
    assert result.claim_differences == ("joy_absent_became_positive",)
