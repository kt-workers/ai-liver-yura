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
    def __init__(self, observations: list[dict[str, object]]) -> None:
        self.observations = observations
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        if activity.context.get("llm_role") == "character_realization_observer":
            return json.dumps({"observations": self.observations}, ensure_ascii=False)
        checks = []
        for observation in self.observations:
            realization_id = str(observation["realization_id"])
            predicate_spans = list(observation.get("predicate_evidence_spans") or [])
            checks.append(
                {
                    "realization_id": realization_id,
                    "predicate_preserved": True,
                    "predicate_evidence_spans": predicate_spans,
                    "concept_preserved": True,
                    "concept_evidence_spans": [],
                }
            )
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
                "realized_proposition_checks": checks,
            },
            ensure_ascii=False,
        )


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
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ直接答える",
        source_event_id=f"state-fidelity-{target_id}",
        context={
            "activity_execution_result": result,
            "event_payload": {
                "text": user_text,
                "activity_execution_result": result,
                "emotion": emotion,
            },
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


def _observation(
    realization_id: str,
    *,
    state: str,
    certainty: str,
    predicate_evidence: str,
    state_evidence: str,
    certainty_evidence: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "realization_id": realization_id,
        "predicate_realized": True,
        "observed_state": state,
        "observed_certainty": certainty,
        "predicate_evidence_spans": [predicate_evidence],
        "state_evidence_spans": [state_evidence],
        "certainty_evidence_spans": list(certainty_evidence),
    }


async def _realize_and_validate(
    source: Activity,
    context,
    *,
    speech: str,
    realization_ids: tuple[str, ...],
    observations: list[dict[str, object]],
):
    character_model = _CharacterModel(speech, realization_ids)
    response = await CharacterLanguageRealizerService(
        character_model,
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    ).generate(source, context)

    validator_model = _ValidatorModel(observations)
    validation = await CharacterRealizationValidator(
        model=validator_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(source, context, response)
    return response, validation, character_model, validator_model


@pytest.mark.asyncio
async def test_high_joy_bare_presence_is_rejected_by_independent_observer() -> None:
    source, context, plan = _source_and_context(
        target_id="joy",
        user_text="楽しい？",
        emotion={"current": {"reactive": {"joy": 0.78}}},
    )
    assert plan.propositions[0].state == "high"

    _, validation, _, validator_model = await _realize_and_validate(
        source,
        context,
        speech="うん、楽しいよ。",
        realization_ids=("proposition:0:joy",),
        observations=[
            _observation(
                "proposition:0:joy",
                state="present",
                certainty="high",
                predicate_evidence="楽しい",
                state_evidence="楽しい",
            )
        ],
    )

    assert len(validator_model.activities) == 1
    assert validation.accepted is False
    assert validation.reason == "observed_semantic_state_mismatch"


@pytest.mark.asyncio
async def test_missing_sadness_unknown_committed_is_rejected_by_independent_observer() -> None:
    source, context, plan = _source_and_context(
        target_id="sadness",
        user_text="悲しい？",
        emotion={"current": {"reactive": {"joy": 0.22, "anger": 0.0}}},
    )
    assert plan.propositions[0].state == "unknown"
    assert plan.propositions[0].certainty == "low"

    _, validation, _, _ = await _realize_and_validate(
        source,
        context,
        speech="ううん、悲しいとは言えないかな。",
        realization_ids=("proposition:0:sadness",),
        observations=[
            _observation(
                "proposition:0:sadness",
                state="absent",
                certainty="low",
                predicate_evidence="悲しい",
                state_evidence="悲しいとは言えない",
                certainty_evidence=("かな",),
            )
        ],
    )

    assert validation.accepted is False
    assert validation.reason == "observed_semantic_state_mismatch"


@pytest.mark.asyncio
async def test_explicit_null_sadness_unknown_exact_is_accepted() -> None:
    source, context, plan = _source_and_context(
        target_id="sadness",
        user_text="悲しい？",
        emotion={"current": {"reactive": {"joy": 0.22, "anger": 0.0, "sadness": None}}},
    )
    assert plan.propositions[0].state == "unknown"
    assert plan.propositions[0].certainty == "high"

    _, validation, _, validator_model = await _realize_and_validate(
        source,
        context,
        speech="今は、悲しいかどうかは判断できないよ。",
        realization_ids=("proposition:0:sadness",),
        observations=[
            _observation(
                "proposition:0:sadness",
                state="unknown",
                certainty="high",
                predicate_evidence="悲しい",
                state_evidence="判断できない",
            )
        ],
    )

    assert validation.accepted is True
    assert validation.reason == "post_observation_semantic_contract_consistent"
    assert len(validator_model.activities) == 2


@pytest.mark.asyncio
async def test_mixed_supporting_bare_presence_is_rejected_by_independent_observer() -> None:
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
    _, validation, _, _ = await _realize_and_validate(
        source,
        context,
        speech="今の気分は、穏やかで、うれしさがありつつ、少し腹立たしさもあります。",
        realization_ids=realization_ids,
        observations=[
            _observation("proposition:0:current_feeling", state="overview", certainty="high", predicate_evidence="気分", state_evidence="今の気分"),
            _observation("proposition:1:joy", state="present", certainty="high", predicate_evidence="うれしさ", state_evidence="うれしさがあり"),
            _observation("proposition:2:anger", state="moderate", certainty="high", predicate_evidence="腹立たし", state_evidence="少し腹立たし"),
            _observation("proposition:3:calm", state="present", certainty="high", predicate_evidence="穏やか", state_evidence="穏やか"),
        ],
    )

    assert validation.accepted is False
    assert validation.reason == "observed_semantic_state_mismatch"
    assert any("proposition:1:joy:observed_state_mismatch" in item for item in validation.claim_differences)
    assert any("proposition:3:calm:observed_state_mismatch" in item for item in validation.claim_differences)


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

    _, validation, character_model, validator_model = await _realize_and_validate(
        source,
        context,
        speech="今はかなりうれしくて、腹立たしさもそこそこある気分だよ。",
        realization_ids=realization_ids,
        observations=[
            _observation("proposition:0:current_feeling", state="overview", certainty="high", predicate_evidence="気分", state_evidence="気分"),
            _observation("proposition:1:joy", state="high", certainty="high", predicate_evidence="うれし", state_evidence="かなりうれしく"),
            _observation("proposition:2:anger", state="moderate", certainty="high", predicate_evidence="腹立たし", state_evidence="そこそこ"),
        ],
    )

    assert validation.accepted is True
    assert validation.reason == "post_observation_semantic_contract_consistent"
    assert len(validator_model.activities) == 2

    forbidden_keys = {
        "user_input",
        "response_context",
        "emotion",
        "drive",
        "event_payload",
        "activity_execution_result",
        "ongoing_activity",
    }
    for invocation in (
        character_model.activities[0],
        validator_model.activities[0],
        validator_model.activities[1],
    ):
        assert invocation.context["semantic_boundary"] is True
        assert forbidden_keys.isdisjoint(invocation.context.keys())
