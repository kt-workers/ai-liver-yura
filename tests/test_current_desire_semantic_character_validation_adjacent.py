from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.runtime.character_language_realizer_service import CharacterLanguageRealizerService
from app.runtime.character_realization_validator import CharacterRealizationValidator
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner
from app.runtime.semantic_utterance_validator import SemanticUtteranceValidator


class _CharacterModel:
    def __init__(
        self,
        speech: str = "うん、好奇心から何かしたい気持ちはあると思うよ。",
    ) -> None:
        self.speech = speech
        self.activities: list[Activity] = []

    async def generate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return json.dumps(
            {
                "speech": self.speech,
                "linguistic_performance": {
                    "phrasing": [self.speech],
                    "emphasis": ["好奇心"],
                    "delivery_tags": ["gentle"],
                },
                "semantic_realizations": ["proposition:0:current_desire"],
            },
            ensure_ascii=False,
        )


class _ValidatorModel:
    def __init__(self, *, predicate_preserved: bool = True) -> None:
        self.predicate_preserved = predicate_preserved
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return json.dumps(
            {
                "accepted": True,
                "reason": "semantic_realization_consistent",
                "differences": [],
                "semantic_checks": {
                    "required_facets_preserved": True,
                    "predicate_preserved": self.predicate_preserved,
                    "state_preserved": True,
                    "certainty_preserved": True,
                    "concept_preserved": True,
                    "unsupported_intensity_added": False,
                },
                "surface_evidence": {"intensity_markers": []},
            },
            ensure_ascii=False,
        )


def _context() -> ResponseContext:
    return ResponseContext(
        user_input="何かしたい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の欲求へ直接答える",
        speech_act="question",
        memory={
            "response_content_plan": {
                "primary_desire": "curiosity",
                "conversation_strategies": [],
                "value_emphases": [],
                "interpersonal_stance": "balanced",
                "expression_mode": "balanced",
                "self_disclosure_level": "none",
                "conflict_mode": None,
                "question_budget": 0,
                "new_direction_budget": 0,
                "observation_only": True,
                "reasons": ["motivation_projected_to_response_content"],
            }
        },
        constraints={
            "_internal_directive": {
                "structured_input_meaning": {
                    "input_speech_act": "question",
                    "primary_intent": "ask_internal_state",
                    "expected_response": "direct_answer",
                    "target": {"type": "internal_state", "id": "current_desire"},
                },
                "internal_directive": {
                    "response_mode": "answer",
                    "response_goal": "現在の欲求へ自然に直接答える",
                    "question_budget": 0,
                    "new_direction_budget": 0,
                    "self_disclosure_level": 0.35,
                    "content_requirements": [],
                    "forbidden_claims": [],
                },
            }
        },
    )


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つ",
        speaking_style="やわらかく自然な話し方",
        streaming_style="会話相手へ自然に反応する",
    )


def _validated_context() -> tuple[ResponseContext, Activity]:
    context = _context()
    plan = ResponseSemanticsPlanner().plan(context)
    assert plan.propositions[0].predicate == "current_desire"
    assert plan.propositions[0].state == "present"
    assert plan.propositions[0].certainty == "medium"
    assert plan.propositions[0].concept == "curiosity"
    assert plan.propositions[0].evidence_refs == (
        "response_content_plan.primary_desire",
    )

    semantic_validation = SemanticUtteranceValidator().validate(context, plan)
    assert semantic_validation.accepted is True

    validated = replace(
        context,
        memory={
            **context.memory,
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": semantic_validation.as_context(),
        },
    )
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="現在の欲求へ直接答える",
        source_event_id="current-desire-adjacent",
        context={
            "event_id": "current-desire-adjacent",
            "trace_context": {"trace_id": "trace-current-desire"},
            "activity_turn_id": "turn-current-desire",
        },
    )
    return validated, source


@pytest.mark.asyncio
async def test_current_desire_medium_certainty_flows_through_semantic_character_validator_boundary() -> None:
    context, source = _validated_context()

    character_model = _CharacterModel()
    realizer = CharacterLanguageRealizerService(
        character_model,
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    )
    response = await realizer.generate(source, context)

    character_prompt = character_model.activities[0].context["plugin_prompt_override"]
    assert '"required_facets": ["predicate", "state", "certainty", "concept"]' in character_prompt
    assert '"predicate_semantics": "preserve_target_meaning"' in character_prompt
    assert '"state_semantics": "presence_without_intensity"' in character_prompt
    assert '"certainty_semantics": "epistemic_not_intensity"' in character_prompt
    assert '"certainty_realization": "epistemic_modality"' in character_prompt
    assert '"intensity_allowed": false' in character_prompt
    assert '"concept_role": "modify_predicate_not_replace_it"' in character_prompt
    assert "response_content_plan.primary_desire" not in character_prompt
    assert "少し" not in response.speech
    assert "ちょっと" not in response.speech

    validator_model = _ValidatorModel(predicate_preserved=True)
    validator = CharacterRealizationValidator(
        model=validator_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    result = await validator.validate(source, context, response)

    assert len(validator_model.activities) == 1
    validator_prompt = validator_model.activities[0].context["plugin_prompt_override"]
    assert '"required_facets": ["predicate", "state", "certainty", "concept"]' in validator_prompt
    assert '"predicate_semantics": "preserve_target_meaning"' in validator_prompt
    assert '"state": "present"' in validator_prompt
    assert '"certainty": "medium"' in validator_prompt
    assert '"concept": "curiosity"' in validator_prompt
    assert result.accepted is True
    assert result.reason == "semantic_realization_consistent"

    forbidden = {
        "user_input",
        "response_context",
        "emotion",
        "drive",
        "event_payload",
        "activity_execution_result",
    }
    for invocation in (character_model.activities[0], validator_model.activities[0]):
        assert invocation.context["semantic_boundary"] is True
        assert forbidden.isdisjoint(invocation.context.keys())


@pytest.mark.asyncio
async def test_concept_only_current_desire_realization_is_rejected_even_if_model_accepts() -> None:
    context, source = _validated_context()
    character_model = _CharacterModel("うん、気になる感じはあるよ。")
    response = await CharacterLanguageRealizerService(
        character_model,
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    ).generate(source, context)

    assert response.semantic_realizations == ("proposition:0:current_desire",)
    assert response.speech == "うん、気になる感じはあるよ。"

    validator_model = _ValidatorModel(predicate_preserved=False)
    result = await CharacterRealizationValidator(
        model=validator_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(source, context, response)

    assert len(validator_model.activities) == 1
    assert result.accepted is False
    assert result.reason == "semantic_facet_validation_failed"
    assert "predicate_preserved" in result.claim_differences
