from __future__ import annotations

import json

import pytest

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.character_language_realizer_service import CharacterLanguageRealizerService
from app.runtime.character_realization_validator import CharacterRealizationValidator
from app.runtime.semantic_validated_response_context import SemanticValidatedResponseContextBuilder


class _CharacterModel:
    def __init__(self, speech: str) -> None:
        self.speech = speech
        self.activities: list[Activity] = []

    async def generate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return json.dumps(
            {
                "speech": self.speech,
                "linguistic_performance": {
                    "phrasing": [self.speech],
                    "emphasis": [],
                    "delivery_tags": ["gentle"],
                },
                "semantic_realizations": ["proposition:0:joy"],
            },
            ensure_ascii=False,
        )


class _ValidatorModel:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        observed_state: str,
        state_evidence: str,
    ) -> None:
        self.payload = payload
        self.observed_state = observed_state
        self.state_evidence = state_evidence
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        if activity.context.get("llm_role") == "character_realization_observer":
            return json.dumps(
                {
                    "observations": [
                        {
                            "realization_id": "proposition:0:joy",
                            "predicate_realized": True,
                            "observed_state": self.observed_state,
                            "observed_certainty": "high",
                            "predicate_evidence_spans": ["楽しい"],
                            "state_evidence_spans": [self.state_evidence],
                            "certainty_evidence_spans": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(self.payload, ensure_ascii=False)


def _source_and_context():
    envelope = {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": "joy"},
        },
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "現在の楽しさへ自然に直接答える",
            "question_budget": 0,
            "new_direction_budget": 0,
            "self_disclosure_level": 0.35,
            "content_requirements": [],
            "forbidden_claims": [],
        },
        "existence_boundaries": ["根拠のない実体験を作らない"],
    }
    result = ActivityExecutionResult(
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        constraints={"_internal_directive": envelope},
    )
    payload = {
        "text": "楽しい？",
        "activity_execution_result": result,
        "emotion": {"current": {"reactive": {"joy": 0.78}}},
        "drive": {"curiosity": 0.48, "energy": 0.8},
    }
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ直接答える",
        source_event_id="e1-intensity-evidence",
        context={
            "activity_execution_result": result,
            "event_payload": payload,
            "trace_context": {"trace_id": "trace-e1"},
            "activity_turn_id": "turn-e1",
        },
    )
    context = SemanticValidatedResponseContextBuilder().build(source)
    plan = SemanticUtterancePlan.from_context(context.memory.get("semantic_utterance_plan"))
    assert plan is not None
    assert plan.propositions[0].predicate == "joy"
    assert plan.propositions[0].state == "high"
    assert plan.propositions[0].certainty == "high"
    assert context.memory["semantic_validation"]["accepted"] is True
    return source, context


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つ",
        speaking_style="やわらかく自然な話し方",
        streaming_style="会話相手へ自然に反応する",
    )


def _validation_payload(
    *,
    state_fidelity: str,
    intensity_semantics_preserved: bool,
    presence_only_counterfactual_equivalent: bool,
    evidence_spans: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "accepted": True,
        "reason": "semantic_realization_consistent",
        "differences": [],
        "semantic_checks": {
            "required_facets_preserved": True,
            "predicate_preserved": True,
            "state_preserved": state_fidelity == "exact",
            "certainty_preserved": True,
            "concept_preserved": True,
            "unsupported_intensity_added": False,
        },
        "realized_proposition_checks": [
            {
                "realization_id": "proposition:0:joy",
                "predicate_preserved": True,
                "predicate_evidence_spans": ["楽しい"],
                "state_preserved": state_fidelity == "exact",
                "state_fidelity": state_fidelity,
                "certainty_preserved": True,
                "certainty_evidence_spans": [],
                "concept_preserved": True,
                "concept_evidence_spans": [],
                "intensity_semantics_preserved": intensity_semantics_preserved,
                "presence_only_counterfactual_equivalent": (
                    presence_only_counterfactual_equivalent
                ),
                "intensity_evidence_spans": list(evidence_spans),
            }
        ],
        "surface_evidence": {"intensity_markers": []},
    }


async def _run(
    speech: str,
    payload: dict[str, object],
    *,
    observed_state: str,
    state_evidence: str,
):
    source, context = _source_and_context()
    character_model = _CharacterModel(speech)
    response = await CharacterLanguageRealizerService(
        character_model,
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    ).generate(source, context)

    validator_model = _ValidatorModel(
        payload,
        observed_state=observed_state,
        state_evidence=state_evidence,
    )
    validation = await CharacterRealizationValidator(
        model=validator_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(source, context, response)
    return validation, character_model, validator_model


@pytest.mark.asyncio
async def test_e1_bare_presence_is_rejected_by_independent_observer() -> None:
    validation, character_model, validator_model = await _run(
        "うん、楽しいよ。",
        _validation_payload(
            state_fidelity="exact",
            intensity_semantics_preserved=True,
            presence_only_counterfactual_equivalent=False,
            evidence_spans=(),
        ),
        observed_state="present",
        state_evidence="楽しい",
    )

    assert validation.accepted is False
    assert validation.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:joy:observed_state_mismatch:expected=high:observed=present"
        in validation.claim_differences
    )
    assert len(character_model.activities) == 1
    assert len(validator_model.activities) == 1
    assert validator_model.activities[0].context["llm_role"] == "character_realization_observer"


@pytest.mark.asyncio
async def test_plan_aware_counterfactual_diagnosis_is_rejected_after_observer_passes() -> None:
    validation, _, validator_model = await _run(
        "うん、かなり楽しいよ。",
        _validation_payload(
            state_fidelity="weakened",
            intensity_semantics_preserved=False,
            presence_only_counterfactual_equivalent=True,
            evidence_spans=("かなり",),
        ),
        observed_state="high",
        state_evidence="かなり楽しい",
    )

    assert validation.accepted is False
    assert validation.reason == "semantic_facet_validation_failed"
    assert "proposition:0:joy:state_fidelity:weakened" in validation.claim_differences
    assert "proposition:0:joy:intensity_semantics_preserved" in validation.claim_differences
    assert (
        "proposition:0:joy:presence_only_counterfactual_equivalent"
        in validation.claim_differences
    )
    assert len(validator_model.activities) == 2


@pytest.mark.asyncio
async def test_e1_exact_with_actual_speech_evidence_accepts_and_boundaries_are_sanitized() -> None:
    validation, character_model, validator_model = await _run(
        "うん、すごく楽しいよ。",
        _validation_payload(
            state_fidelity="exact",
            intensity_semantics_preserved=True,
            presence_only_counterfactual_equivalent=False,
            evidence_spans=("すごく",),
        ),
        observed_state="high",
        state_evidence="すごく楽しい",
    )

    assert validation.accepted is True
    assert validation.reason == "semantic_realization_consistent"
    assert len(validator_model.activities) == 2

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
        validator_model.activities[0],
        validator_model.activities[1],
    ):
        assert invocation.context["semantic_boundary"] is True
        assert forbidden.isdisjoint(invocation.context.keys())
