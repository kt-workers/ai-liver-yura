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
    def __init__(
        self,
        response: str,
        *,
        observation: dict[str, object] | None = None,
    ) -> None:
        self.response = response
        self.observation = observation or _observation()
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        if activity.context.get("llm_role") == "character_realization_observer":
            return json.dumps(
                {"observations": [self.observation]},
                ensure_ascii=False,
            )
        return self.response


def _observation(
    *,
    state: str = "absent",
    certainty: str = "high",
    predicate_realized: bool = True,
    predicate_spans: tuple[str, ...] = ("楽しくない",),
    state_spans: tuple[str, ...] = ("楽しくない",),
    certainty_spans: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "realization_id": "proposition:0:joy",
        "predicate_realized": predicate_realized,
        "observed_state": state,
        "observed_certainty": certainty,
        "predicate_evidence_spans": list(predicate_spans),
        "state_evidence_spans": list(state_spans),
        "certainty_evidence_spans": list(certainty_spans),
    }


def _accepted_payload(*, intensity_markers: list[str] | None = None) -> dict[str, object]:
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
        "realized_proposition_checks": [
            {
                "realization_id": "proposition:0:joy",
                "predicate_preserved": True,
                "predicate_evidence_spans": ["楽しくない"],
                "state_preserved": True,
                "state_fidelity": "exact",
                "certainty_preserved": True,
                "certainty_evidence_spans": [],
                "concept_preserved": True,
                "concept_evidence_spans": [],
                "intensity_semantics_preserved": True,
                "presence_only_counterfactual_equivalent": False,
                "intensity_evidence_spans": [],
            }
        ],
        "surface_evidence": {
            "intensity_markers": intensity_markers or [],
        },
    }


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
    speech: str = "今は楽しくないよ。",
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
    prompt = CharacterRealizationValidatorPromptBuilder().build(context, _response())
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
    assert "surface_evidence.intensity_markers" in prompt
    assert "semantic_checks" in prompt


@pytest.mark.asyncio
async def test_realization_validator_model_invocations_are_sanitized() -> None:
    model = _RecordingValidationModel(json.dumps(_accepted_payload(), ensure_ascii=False))
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
    assert len(model.activities) == 2
    observer, comparator = model.activities
    assert observer.context["llm_role"] == "character_realization_observer"
    assert comparator.context["llm_role"] == "character_realization_validator"
    for activity in model.activities:
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


@pytest.mark.asyncio
async def test_missing_primary_semantic_realization_is_rejected_before_model_call() -> None:
    model = _RecordingValidationModel(json.dumps(_accepted_payload()))
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="質問へ答える")
    result = await validator.validate(
        source,
        _validated_context(),
        _response(realizations=()),
    )
    assert result.accepted is False
    assert result.reason == "required_semantic_realization_missing"
    assert model.activities == []


@pytest.mark.asyncio
async def test_plan_aware_model_rejection_is_returned_after_observer_passes() -> None:
    model = _RecordingValidationModel(
        json.dumps(
            {
                "accepted": False,
                "reason": "target_polarity_changed",
                "differences": ["validator_reported_difference"],
            },
            ensure_ascii=False,
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="質問へ答える")
    result = await validator.validate(source, _validated_context(), _response())
    assert result.accepted is False
    assert result.reason == "target_polarity_changed"
    assert result.claim_differences == ("validator_reported_difference",)
    assert len(model.activities) == 2


@pytest.mark.asyncio
async def test_surface_marker_is_diagnostic_only_when_typed_semantics_match() -> None:
    model = _RecordingValidationModel(
        json.dumps(_accepted_payload(intensity_markers=["今は"]), ensure_ascii=False)
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="質問へ答える")
    result = await validator.validate(source, _validated_context(), _response())
    assert result.accepted is True
    assert result.reason == "semantic_realization_consistent"


@pytest.mark.asyncio
async def test_semantic_change_is_rejected_by_independent_observer_without_word_dictionary() -> None:
    model = _RecordingValidationModel(
        json.dumps(_accepted_payload(), ensure_ascii=False),
        observation=_observation(
            state="low",
            certainty="medium",
            predicate_spans=("楽しくない",),
            state_spans=("少し楽しくない",),
            certainty_spans=("かな",),
        ),
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="質問へ答える")
    result = await validator.validate(
        source,
        _validated_context(),
        _response(speech="少し楽しくないかな。"),
    )
    assert result.accepted is False
    assert result.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:joy:observed_state_mismatch:expected=absent:observed=low"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_semantic_path_without_validator_model_fails_closed_without_lexical_fallback() -> None:
    validator = CharacterRealizationValidator(
        model=None,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="質問へ答える")
    result = await validator.validate(
        source,
        _validated_context(),
        _response(speech="少し楽しくないかな。"),
    )
    assert result.accepted is False
    assert result.reason == "realization_validator_model_unavailable"
    assert result.claim_differences == ()


@pytest.mark.asyncio
async def test_model_acceptance_without_facet_diagnostics_fails_closed() -> None:
    model = _RecordingValidationModel(
        json.dumps(
            {
                "accepted": True,
                "reason": "semantic_realization_consistent",
                "differences": [],
            }
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    source = Activity(activity_type=ActivityType.CONVERSATION_WITH_USER, goal="質問へ答える")
    result = await validator.validate(source, _validated_context(), _response())
    assert result.accepted is False
    assert result.reason == "realization_validator_schema_invalid"
