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
    def __init__(self, speech: str, realization_ids: tuple[str, ...]) -> None:
        self.speech = speech
        self.realization_ids = realization_ids
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
                "semantic_realizations": list(self.realization_ids),
            },
            ensure_ascii=False,
        )


class _ValidatorModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return json.dumps(self.payload, ensure_ascii=False)


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つ",
        speaking_style="やわらかく自然な話し方",
        streaming_style="会話相手へ自然に反応する",
    )


def _source_and_context(
    *,
    target_id: str,
    user_text: str,
    emotion: dict[str, object],
):
    envelope = {
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
        "existence_boundaries": ["根拠のない実体験を作らない"],
    }
    result = ActivityExecutionResult(
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        constraints={"_internal_directive": envelope},
    )
    payload: dict[str, object] = {
        "text": user_text,
        "activity_execution_result": result,
        "emotion": emotion,
    }
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ直接答える",
        source_event_id=f"state-fidelity-{target_id}",
        context={
            "activity_execution_result": result,
            "event_payload": payload,
            "trace_context": {"trace_id": f"trace-{target_id}"},
            "activity_turn_id": f"turn-{target_id}",
        },
    )
    context = SemanticValidatedResponseContextBuilder().build(source)
    plan = SemanticUtterancePlan.from_context(
        context.memory.get("semantic_utterance_plan")
    )
    assert plan is not None
    assert context.memory["semantic_validation"]["accepted"] is True
    return source, context, plan


def _predicate_evidence(realization_id: str) -> tuple[str, ...]:
    return {
        "proposition:0:joy": ("楽しい",),
        "proposition:0:sadness": ("悲しい",),
        "proposition:0:current_feeling": ("気分",),
        "proposition:1:joy": ("うれし",),
        "proposition:2:anger": ("腹立たし",),
        "proposition:3:calm": ("穏やか",),
    }.get(realization_id, ())


def _check(
    realization_id: str,
    state_fidelity: str = "exact",
    *,
    intensity_semantics_preserved: bool = True,
    presence_only_counterfactual_equivalent: bool = False,
    intensity_evidence_spans: tuple[str, ...] = (),
    certainty_evidence_spans: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "realization_id": realization_id,
        "predicate_preserved": True,
        "predicate_evidence_spans": list(_predicate_evidence(realization_id)),
        "state_preserved": state_fidelity == "exact",
        "state_fidelity": state_fidelity,
        "certainty_preserved": True,
        "certainty_evidence_spans": list(certainty_evidence_spans),
        "concept_preserved": True,
        "concept_evidence_spans": [],
        "intensity_semantics_preserved": intensity_semantics_preserved,
        "presence_only_counterfactual_equivalent": (
            presence_only_counterfactual_equivalent
        ),
        "intensity_evidence_spans": list(intensity_evidence_spans),
    }


def _accepted_payload(checks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "accepted": True,
        "reason": "semantic_realization_consistent",
        "differences": [],
        "semantic_checks": {
            "required_facets_preserved": True,
            "predicate_preserved": True,
            "state_preserved": True,
            "certainty_preserved": True,
            "concept_preserved": True,
            "unsupported_intensity_added": False,
        },
        "realized_proposition_checks": checks,
        "surface_evidence": {"intensity_markers": []},
    }


async def _realize_and_validate(
    source: Activity,
    context,
    *,
    speech: str,
    realization_ids: tuple[str, ...],
    validation_payload: dict[str, object],
):
    character_model = _CharacterModel(speech, realization_ids)
    response = await CharacterLanguageRealizerService(
        character_model,
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    ).generate(source, context)

    validator_model = _ValidatorModel(validation_payload)
    validation = await CharacterRealizationValidator(
        model=validator_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(source, context, response)
    return response, validation, character_model, validator_model


@pytest.mark.asyncio
async def test_high_joy_weakened_diagnosis_is_rejected_after_production_plan() -> None:
    source, context, plan = _source_and_context(
        target_id="joy",
        user_text="楽しい？",
        emotion={"current": {"reactive": {"joy": 0.78}}},
    )
    assert plan.propositions[0].predicate == "joy"
    assert plan.propositions[0].state == "high"
    assert plan.propositions[0].certainty == "high"

    _, validation, _, validator_model = await _realize_and_validate(
        source,
        context,
        speech="うん、楽しいよ。",
        realization_ids=("proposition:0:joy",),
        validation_payload=_accepted_payload(
            [
                _check(
                    "proposition:0:joy",
                    "weakened",
                    intensity_semantics_preserved=False,
                    presence_only_counterfactual_equivalent=True,
                )
            ]
        ),
    )

    assert len(validator_model.activities) == 1
    assert validation.accepted is False
    assert validation.reason == "semantic_facet_validation_failed"
    assert "proposition:0:joy:state_fidelity:weakened" in validation.claim_differences


@pytest.mark.asyncio
async def test_missing_sadness_unknown_committed_diagnosis_is_rejected() -> None:
    source, context, plan = _source_and_context(
        target_id="sadness",
        user_text="悲しい？",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.22,
                    "amusement": 0.08,
                    "calm": 0.55,
                    "anger": 0.0,
                }
            }
        },
    )
    assert plan.propositions[0].predicate == "sadness"
    assert plan.propositions[0].state == "unknown"
    assert plan.propositions[0].certainty == "low"

    _, validation, _, _ = await _realize_and_validate(
        source,
        context,
        speech="ううん、悲しいとは言えないかな。",
        realization_ids=("proposition:0:sadness",),
        validation_payload=_accepted_payload(
            [
                _check(
                    "proposition:0:sadness",
                    "unknown_committed",
                    certainty_evidence_spans=("かな",),
                )
            ]
        ),
    )

    assert validation.accepted is False
    assert validation.reason == "semantic_facet_validation_failed"
    assert (
        "proposition:0:sadness:state_fidelity:unknown_committed"
        in validation.claim_differences
    )


@pytest.mark.asyncio
async def test_explicit_null_sadness_unknown_exact_diagnosis_is_accepted() -> None:
    source, context, plan = _source_and_context(
        target_id="sadness",
        user_text="悲しい？",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.22,
                    "amusement": 0.08,
                    "calm": 0.55,
                    "anger": 0.0,
                    "sadness": None,
                }
            }
        },
    )
    assert plan.propositions[0].predicate == "sadness"
    assert plan.propositions[0].state == "unknown"
    assert plan.propositions[0].certainty == "high"

    _, validation, _, _ = await _realize_and_validate(
        source,
        context,
        speech="今は、悲しいかどうかは判断できないよ。",
        realization_ids=("proposition:0:sadness",),
        validation_payload=_accepted_payload([_check("proposition:0:sadness")]),
    )

    assert validation.accepted is True
    assert validation.reason == "semantic_realization_consistent"


@pytest.mark.asyncio
async def test_mixed_supporting_weakened_diagnosis_rejects_even_with_primary_aggregate_true() -> None:
    source, context, plan = _source_and_context(
        target_id="current_feeling",
        user_text="今どんな気分？",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.78,
                    "anger": 0.48,
                    "calm": 0.22,
                    "amusement": 0.02,
                }
            }
        },
    )
    assert {p.predicate: p.state for p in plan.propositions} == {
        "current_feeling": "overview",
        "joy": "high",
        "anger": "moderate",
        "calm": "low",
        "amusement": "absent",
    }

    realization_ids = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
        "proposition:2:anger",
        "proposition:3:calm",
    )
    checks = [
        _check("proposition:0:current_feeling"),
        _check(
            "proposition:1:joy",
            "weakened",
            intensity_semantics_preserved=False,
            presence_only_counterfactual_equivalent=True,
        ),
        _check(
            "proposition:2:anger",
            intensity_evidence_spans=("少し",),
        ),
        _check(
            "proposition:3:calm",
            "weakened",
            intensity_semantics_preserved=False,
            presence_only_counterfactual_equivalent=True,
        ),
    ]
    _, validation, _, _ = await _realize_and_validate(
        source,
        context,
        speech="今の気分は、穏やかで、うれしさがありつつ、少し腹立たしさもあります。",
        realization_ids=realization_ids,
        validation_payload=_accepted_payload(checks),
    )

    assert validation.accepted is False
    assert validation.reason == "semantic_facet_validation_failed"
    assert "proposition:1:joy:state_fidelity:weakened" in validation.claim_differences
    assert "proposition:3:calm:state_fidelity:weakened" in validation.claim_differences


@pytest.mark.asyncio
async def test_all_adopted_mixed_propositions_exact_accept_and_model_boundaries_stay_sanitized() -> None:
    source, context, _ = _source_and_context(
        target_id="current_feeling",
        user_text="今どんな気分？",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.78,
                    "anger": 0.48,
                    "calm": 0.22,
                    "amusement": 0.02,
                }
            }
        },
    )
    realization_ids = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
        "proposition:2:anger",
    )
    checks = [
        _check("proposition:0:current_feeling"),
        _check("proposition:1:joy", intensity_evidence_spans=("かなり",)),
        _check(
            "proposition:2:anger",
            intensity_evidence_spans=("そこそこ",),
        ),
    ]

    _, validation, character_model, validator_model = await _realize_and_validate(
        source,
        context,
        speech="今はかなりうれしくて、腹立たしさもそこそこある気分だよ。",
        realization_ids=realization_ids,
        validation_payload=_accepted_payload(checks),
    )

    assert validation.accepted is True
    assert validation.reason == "semantic_realization_consistent"

    forbidden_keys = {
        "user_input",
        "response_context",
        "emotion",
        "drive",
        "event_payload",
        "activity_execution_result",
        "ongoing_activity",
    }
    for invocation in (character_model.activities[0], validator_model.activities[0]):
        assert invocation.context["semantic_boundary"] is True
        assert forbidden_keys.isdisjoint(invocation.context.keys())
