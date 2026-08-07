from __future__ import annotations

from app.domain.body_instruction import (
    BODY_ACTION_INTENT_CONSTRAINT,
    BODY_EXPRESSION_ACTIVITY_TYPE,
    BodyInstruction,
)
from app.domain.cognitive_direction import (
    ActivityIntent,
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.prompting.body_aware_internal_directive_prompt_builder import (
    BodyAwareInternalDirectivePromptBuilder,
)
from app.runtime.body_aware_internal_directive_validator import (
    BodyAwareInternalDirectiveValidator,
)
from app.runtime.body_aware_separated_situation_evaluator import (
    BodyAwareSeparatedSituationEvaluationAdapter,
)


def _meaning() -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.COMMAND,
        primary_intent="direct_body_action",
        expected_response=ExpectedResponse.ACTION,
        target=InputTarget("agent_body", "explicit_body_direction"),
        body_instruction=BodyInstruction(
            "arm",
            "up",
            side="right",
            magnitude=0.9,
        ),
        confidence=0.98,
        reason="user requests right arm upward movement",
        source_text="右手挙げて",
    )


def _directive(*, with_body_action: bool = True) -> InternalDirective:
    activity_intent = None
    if with_body_action:
        activity_intent = ActivityIntent(
            BODY_EXPRESSION_ACTIVITY_TYPE,
            "start",
            {
                BODY_ACTION_INTENT_CONSTRAINT: BodyInstruction(
                    "arm",
                    "up",
                    side="right",
                    magnitude=0.8,
                ).as_context(),
            },
        )
    return InternalDirective(
        response_mode=ResponseMode.REACT,
        response_goal="要求に自然に応じる",
        activity_intent=activity_intent,
        initiative_level=0.2,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.0,
        reason="conscious action decision",
    )


def test_internal_directive_prompt_separates_requested_body_action_from_yura_decision() -> None:
    prompt = BodyAwareInternalDirectivePromptBuilder().build(
        _meaning(),
        {"available_activities": []},
        character_profile={
            "name": "ゆら",
            "existence": {
                "physical_capabilities": ["物理的な身体を持たない"],
            },
        },
    )

    assert "body_instructionはユーザーが要求した身体行動" in prompt
    assert BODY_EXPRESSION_ACTIVITY_TYPE in prompt
    assert BODY_ACTION_INTENT_CONSTRAINT in prompt
    assert "アバターBodyを動かす能力そのものを否定" in prompt
    assert "実行失敗は後段Runtimeの事実" in prompt


def test_core_validator_accepts_body_activity_chosen_by_internal_directive_without_plugin_registry() -> None:
    plan = BodyAwareInternalDirectiveValidator().validate(
        _meaning(),
        _directive(),
        {"available_activities": []},
        character_profile={"name": "ゆら"},
    )

    intent = plan.directive.activity_intent
    assert intent is not None
    assert intent.activity_type == BODY_EXPRESSION_ACTIVITY_TYPE
    assert intent.operation == "start"
    assert BodyInstruction.from_context(
        intent.constraints[BODY_ACTION_INTENT_CONSTRAINT]
    ) == BodyInstruction("arm", "up", side="right", magnitude=0.8)
    assert "core_body_action_intent_validated" in plan.validation_notes


def test_core_validator_does_not_infer_body_activity_when_directive_did_not_choose_it() -> None:
    plan = BodyAwareInternalDirectiveValidator().validate(
        _meaning(),
        _directive(with_body_action=False),
        {"available_activities": []},
        character_profile={"name": "ゆら"},
    )

    assert plan.directive.activity_intent is None
    assert "core_body_action_intent_validated" not in plan.validation_notes


def test_body_activity_projection_keeps_same_validated_directive_for_character_and_body() -> None:
    plan = BodyAwareInternalDirectiveValidator().validate(
        _meaning(),
        _directive(),
        {"available_activities": []},
        character_profile={"name": "ゆら"},
    )

    payload = BodyAwareSeparatedSituationEvaluationAdapter._legacy_situation_payload(plan)

    assert payload["activity_type"] == BODY_EXPRESSION_ACTIVITY_TYPE
    constraints = payload["constraints"]
    assert isinstance(constraints, dict)
    assert BODY_ACTION_INTENT_CONSTRAINT in constraints
    assert constraints["_internal_directive"] == plan.as_context()
