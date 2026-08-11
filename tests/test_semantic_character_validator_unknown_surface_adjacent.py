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

    async def generate_character_response(self, activity: Activity) -> str:
        return json.dumps(
            {
                "speech": self.speech,
                "linguistic_performance": {
                    "phrasing": [self.speech],
                    "emphasis": [],
                    "delivery_tags": ["gentle"],
                },
                "semantic_realizations": ["proposition:0:sadness"],
            },
            ensure_ascii=False,
        )


class _ValidatorModel:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        observed_state: str,
        observed_certainty: str,
        state_evidence: str,
        certainty_evidence: str | None,
    ) -> None:
        self.payload = payload
        self.observed_state = observed_state
        self.observed_certainty = observed_certainty
        self.state_evidence = state_evidence
        self.certainty_evidence = certainty_evidence

    async def validate_character_response(self, activity: Activity) -> str:
        if activity.context.get("llm_role") == "character_realization_observer":
            return json.dumps(
                {
                    "observations": [
                        {
                            "realization_id": "proposition:0:sadness",
                            "predicate_realized": True,
                            "observed_state": self.observed_state,
                            "observed_certainty": self.observed_certainty,
                            "predicate_evidence_spans": ["悲し"],
                            "state_evidence_spans": [self.state_evidence],
                            "certainty_evidence_spans": (
                                [self.certainty_evidence]
                                if self.certainty_evidence is not None
                                else []
                            ),
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(self.payload, ensure_ascii=False)


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つ",
        speaking_style="やわらかく自然な話し方",
        streaming_style="会話相手へ自然に反応する",
    )


def _source_and_context():
    envelope = {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": "sadness"},
        },
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "現在の悲しさへ自然に直接答える",
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
    emotion = {
        "current": {
            "reactive": {
                "joy": 0.22,
                "amusement": 0.08,
                "calm": 0.55,
                "anger": 0.0,
            }
        }
    }
    payload: dict[str, object] = {
        "text": "悲しい？",
        "activity_execution_result": result,
        "emotion": emotion,
    }
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ直接答える",
        source_event_id="e2-unknown-surface-adjacent",
        context={
            "activity_execution_result": result,
            "event_payload": payload,
            "trace_context": {"trace_id": "trace-e2-unknown"},
            "activity_turn_id": "turn-e2-unknown",
        },
    )
    context = SemanticValidatedResponseContextBuilder().build(source)
    plan = SemanticUtterancePlan.from_context(
        context.memory.get("semantic_utterance_plan")
    )
    assert plan is not None
    assert context.memory["semantic_validation"]["accepted"] is True
    assert plan.propositions[0].predicate == "sadness"
    assert plan.propositions[0].state == "unknown"
    assert plan.propositions[0].certainty == "low"
    return source, context


def _validation_payload(
    *,
    state_fidelity: str = "exact",
    surface_markers: list[str] | None = None,
    certainty_evidence: str = "はっきりしない",
) -> dict[str, object]:
    exact = state_fidelity == "exact"
    return {
        "accepted": True,
        "reason": "semantic_realization_consistent",
        "differences": [],
        "semantic_checks": {
            "required_facets_preserved": exact,
            "predicate_preserved": True,
            "state_preserved": exact,
            "certainty_preserved": exact,
            "concept_preserved": True,
            "unsupported_intensity_added": False,
        },
        "realized_proposition_checks": [
            {
                "realization_id": "proposition:0:sadness",
                "predicate_preserved": True,
                "predicate_evidence_spans": ["悲し"],
                "state_preserved": exact,
                "state_fidelity": state_fidelity,
                "certainty_preserved": exact,
                "certainty_evidence_spans": [certainty_evidence] if exact else [],
                "concept_preserved": True,
                "concept_evidence_spans": [],
                "intensity_semantics_preserved": True,
                "presence_only_counterfactual_equivalent": False,
                "intensity_evidence_spans": [],
            }
        ],
        "surface_evidence": {
            "intensity_markers": list(surface_markers or []),
        },
    }


async def _run(
    *,
    speech: str,
    validator_payload: dict[str, object],
    observed_state: str,
    observed_certainty: str,
    state_evidence: str,
    certainty_evidence: str | None,
):
    source, context = _source_and_context()
    response = await CharacterLanguageRealizerService(
        _CharacterModel(speech),
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    ).generate(source, context)
    validation = await CharacterRealizationValidator(
        model=_ValidatorModel(
            validator_payload,
            observed_state=observed_state,
            observed_certainty=observed_certainty,
            state_evidence=state_evidence,
            certainty_evidence=certainty_evidence,
        ),
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(source, context, response)
    return validation


@pytest.mark.asyncio
async def test_valid_unknown_survives_spurious_model_surface_markers() -> None:
    validation = await _run(
        speech="今のところ、悲しさはあるかどうか、はっきりしないよ。",
        validator_payload=_validation_payload(
            surface_markers=["今のところ", "はっきりしない"]
        ),
        observed_state="unknown",
        observed_certainty="low",
        state_evidence="はっきりしない",
        certainty_evidence="はっきりしない",
    )

    assert validation.accepted is True
    assert validation.reason == "semantic_realization_consistent"
    assert validation.claim_differences == ()


@pytest.mark.asyncio
async def test_actual_unknown_to_low_commit_is_rejected_by_independent_observer() -> None:
    validation = await _run(
        speech="少し悲しいかも。",
        validator_payload=_validation_payload(certainty_evidence="かも"),
        observed_state="low",
        observed_certainty="low",
        state_evidence="少し悲しい",
        certainty_evidence="かも",
    )

    assert validation.accepted is False
    assert validation.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:sadness:observed_state_mismatch:expected=unknown:observed=low"
        in validation.claim_differences
    )


@pytest.mark.asyncio
async def test_unknown_committed_to_present_is_rejected_by_independent_observer() -> None:
    validation = await _run(
        speech="うん、悲しいよ。",
        validator_payload=_validation_payload(state_fidelity="unknown_committed"),
        observed_state="present",
        observed_certainty="high",
        state_evidence="悲しい",
        certainty_evidence=None,
    )

    assert validation.accepted is False
    assert validation.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:sadness:observed_state_mismatch:expected=unknown:observed=present"
        in validation.claim_differences
    )
