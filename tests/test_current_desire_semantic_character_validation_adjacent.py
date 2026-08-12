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
        if activity.context.get("llm_role") == "character_realization_observer":
            if self.predicate_preserved:
                return json.dumps(
                    {
                        "observations": [
                            {
                                "realization_id": "proposition:0:current_desire",
                                "predicate_realized": True,
                                "observed_state": "present",
                                "observed_certainty": "medium",
                                "predicate_evidence_spans": ["何かしたい気持ち"],
                                "state_evidence_spans": ["気持ちはある"],
                                "certainty_evidence_spans": ["と思う"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "observations": [
                        {
                            "realization_id": "proposition:0:current_desire",
                            "predicate_realized": False,
                            "observed_state": "present",
                            "observed_certainty": "high",
                            "predicate_evidence_spans": [],
                            "state_evidence_spans": ["感じはある"],
                            "certainty_evidence_spans": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )

        if self.predicate_preserved:
            predicate_spans = ["何かしたい気持ち"]
            concept_spans = ["好奇心"]
        else:
            predicate_spans = []
            concept_spans = ["気になる"]
        return json.dumps(
            {
                "accepted": True,
                "reason": "post_observation_semantic_contract_consistent",
                "differences": [],
                "semantic_checks": {
                    "required_content_preserved": True,
                    "forbidden_additions_absent": True,
                    "unsupported_new_fact_absent": True,
                    "existence_boundary_preserved": True,
                    "budget_preserved": True,
                },
                "realized_proposition_checks": [
                    {
                        "realization_id": "proposition:0:current_desire",
                        "predicate_preserved": self.predicate_preserved,
                        "predicate_evidence_spans": predicate_spans,
                        "concept_preserved": True,
                        "concept_evidence_spans": concept_spans,
                    }
                ],
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


def _post_observation_contract(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    marker = lines.index("# Post-Observation Semantic Contract")
    value = json.loads(lines[marker + 1])
    assert isinstance(value, dict)
    return value


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

    validator_model = _ValidatorModel(predicate_preserved=True)
    validator = CharacterRealizationValidator(
        model=validator_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    result = await validator.validate(source, context, response)

    assert len(validator_model.activities) == 2
    observer_activity, comparator_activity = validator_model.activities
    assert observer_activity.context["llm_role"] == "character_realization_observer"
    assert comparator_activity.context["llm_role"] == "character_realization_validator"

    observer_prompt = observer_activity.context["plugin_prompt_override"]
    assert '"realization_id": "proposition:0:current_desire"' in observer_prompt
    assert '"predicate": "current_desire"' in observer_prompt
    assert '"state": "present"' not in observer_prompt
    assert '"certainty": "medium"' not in observer_prompt
    assert '"concept": "curiosity"' not in observer_prompt
    assert "対象stateについてのepistemic確かさ" in observer_prompt

    validator_prompt = comparator_activity.context["plugin_prompt_override"]
    contract = _post_observation_contract(validator_prompt)
    propositions = contract["propositions"]
    assert isinstance(propositions, list)
    proposition = propositions[0]
    assert isinstance(proposition, dict)
    assert proposition["predicate"] == "current_desire"
    assert proposition["concept"] == "curiosity"
    assert "state" not in proposition
    assert "certainty" not in proposition
    assert "state/polarity/intensity/certaintyはこの工程で判定しない" in validator_prompt

    assert result.accepted is True
    assert result.reason == "post_observation_semantic_contract_consistent"

    forbidden = {
        "user_input",
        "response_context",
        "emotion",
        "drive",
        "event_payload",
        "activity_execution_result",
    }
    for invocation in (
        character_model.activities[0],
        observer_activity,
        comparator_activity,
    ):
        assert invocation.context["semantic_boundary"] is True
        assert forbidden.isdisjoint(invocation.context.keys())


@pytest.mark.asyncio
async def test_concept_only_current_desire_realization_is_rejected_by_independent_observer() -> None:
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
    assert validator_model.activities[0].context["llm_role"] == "character_realization_observer"
    assert result.accepted is False
    assert result.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:current_desire:predicate_not_observed"
        in result.claim_differences
    )
