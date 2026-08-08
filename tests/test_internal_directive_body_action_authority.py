from __future__ import annotations

import json

import pytest

from app.domain.behavior import BehaviorDecision, BehaviorPlanningContext
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
from app.runtime.body_aware_behavior_planner import BodyAwareBehaviorPlanner
from app.runtime.body_aware_internal_directive_validator import (
    BodyAwareInternalDirectiveValidator,
)
from app.runtime.body_aware_separated_situation_evaluator import (
    BodyAwareSeparatedSituationEvaluationAdapter,
)
from app.runtime.situation_evaluator import SituationEvaluator


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


class _NeverSituationModel:
    async def evaluate(self, activity: object) -> str:
        raise AssertionError("parse-only regression helper must not call model")


class _NeverSituationPromptBuilder:
    def build(self, context: object) -> str:
        raise AssertionError("parse-only regression helper must not build prompt")


class _PayloadParsingSituationEvaluator:
    """実Situation schema parserでPlanning Context候補を検証する回帰Helper。"""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self._parser = SituationEvaluator(
            _NeverSituationModel(),
            prompt_builder=_NeverSituationPromptBuilder(),
        )
        self.seen_activity_types: tuple[str, ...] = ()

    async def evaluate(self, context: BehaviorPlanningContext):  # type: ignore[no-untyped-def]
        self.seen_activity_types = tuple(
            definition.activity_type for definition in context.activity_definitions
        )
        parsed = self._parser.parse(
            json.dumps(self._payload, ensure_ascii=False),
            context.activity_definitions,
        )
        if parsed is None:
            raise AssertionError("Core-owned Body Activity must pass Situation schema")
        return parsed


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


@pytest.mark.asyncio
async def test_body_activity_passes_real_situation_schema_before_runtime_planning() -> None:
    """実画面FAIL: Directiveは正しいのに候補定義不足でconversationへ落ちる回帰を防ぐ。"""

    validated = BodyAwareInternalDirectiveValidator().validate(
        _meaning(),
        _directive(),
        {"available_activities": []},
        character_profile={"name": "ゆら"},
    )
    payload = BodyAwareSeparatedSituationEvaluationAdapter._legacy_situation_payload(
        validated
    )
    evaluator = _PayloadParsingSituationEvaluator(payload)
    planner = BodyAwareBehaviorPlanner(situation_evaluator=evaluator)
    context = BehaviorPlanningContext(
        user_text="右手挙げて",
        source_event_id="body-directive-full-planning-regression",
        available_capabilities=frozenset(),
        activity_definitions=(),
    )

    analysis = await planner.evaluate_situation(context)
    activity_plan = planner.plan_from_analysis(context, analysis)

    assert BODY_EXPRESSION_ACTIVITY_TYPE in evaluator.seen_activity_types
    assert analysis.activity_candidate == BODY_EXPRESSION_ACTIVITY_TYPE
    assert analysis.evaluator_type == "llm"
    assert activity_plan.decision is BehaviorDecision.START_ACTIVITY
    assert activity_plan.activity_type == BODY_EXPRESSION_ACTIVITY_TYPE
    assert activity_plan.reason == "validated_internal_directive_body_action"
    assert BodyInstruction.from_context(
        activity_plan.constraints[BODY_ACTION_INTENT_CONSTRAINT]
    ) == BodyInstruction("arm", "up", side="right", magnitude=0.8)
    assert "_internal_directive" in activity_plan.constraints
