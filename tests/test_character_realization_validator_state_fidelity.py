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
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)
from app.runtime.character_realization_validator import CharacterRealizationValidator


class _RecordingValidationModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return json.dumps(self.payload, ensure_ascii=False)


def _context(
    *,
    user_input: str,
    target_id: str,
    propositions: tuple[SemanticProposition, ...],
) -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", target_id),
        propositions=propositions,
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input=user_input,
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="内部状態へ直接答える",
        speech_act="question",
        constraints={
            "_internal_directive": {
                "existence_boundaries": ["存在種別はAI VTuberである"],
            }
        },
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
    speech: str,
    realizations: tuple[str, ...],
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


def _predicate_evidence(realization_id: str) -> tuple[str, ...]:
    return {
        "proposition:0:joy": ("楽しい",),
        "proposition:0:sadness": ("悲しい",),
        "proposition:0:current_feeling": ("今の気分",),
        "proposition:1:joy": ("うれし",),
        "proposition:2:anger": ("腹立たし",),
        "proposition:3:calm": ("穏やか",),
        "proposition:4:amusement": ("面白",),
    }.get(realization_id, ())


def _check(
    realization_id: str,
    *,
    state_fidelity: str = "exact",
    predicate_preserved: bool = True,
    state_preserved: bool = True,
    certainty_preserved: bool = True,
    concept_preserved: bool = True,
    intensity_semantics_preserved: bool = True,
    presence_only_counterfactual_equivalent: bool = False,
    intensity_evidence_spans: tuple[str, ...] = (),
    predicate_evidence_spans: tuple[str, ...] | None = None,
    certainty_evidence_spans: tuple[str, ...] = (),
    concept_evidence_spans: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "realization_id": realization_id,
        "predicate_preserved": predicate_preserved,
        "predicate_evidence_spans": list(
            _predicate_evidence(realization_id)
            if predicate_evidence_spans is None
            else predicate_evidence_spans
        ),
        "state_preserved": state_preserved,
        "state_fidelity": state_fidelity,
        "certainty_preserved": certainty_preserved,
        "certainty_evidence_spans": list(certainty_evidence_spans),
        "concept_preserved": concept_preserved,
        "concept_evidence_spans": list(concept_evidence_spans),
        "intensity_semantics_preserved": intensity_semantics_preserved,
        "presence_only_counterfactual_equivalent": (
            presence_only_counterfactual_equivalent
        ),
        "intensity_evidence_spans": list(intensity_evidence_spans),
    }


def _accepted_payload(
    checks: list[dict[str, object]],
    *,
    state_preserved: bool = True,
) -> dict[str, object]:
    return {
        "accepted": True,
        "reason": "semantic_realization_consistent",
        "differences": [],
        "semantic_checks": {
            "required_facets_preserved": True,
            "predicate_preserved": True,
            "state_preserved": state_preserved,
            "certainty_preserved": True,
            "concept_preserved": True,
            "unsupported_intensity_added": False,
        },
        "realized_proposition_checks": checks,
        "surface_evidence": {"intensity_markers": []},
    }


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="state-fidelity-test",
    )


def _joy_high_context() -> ResponseContext:
    return _context(
        user_input="楽しい？",
        target_id="joy",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
            ),
        ),
    )


def _sadness_unknown_context(*, certainty: str = "high") -> ResponseContext:
    return _context(
        user_input="悲しい？",
        target_id="sadness",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="sadness",
                state="unknown",
                certainty=certainty,
                concept=None,
            ),
        ),
    )


def _mixed_context() -> ResponseContext:
    return _context(
        user_input="今どんな気分？",
        target_id="current_feeling",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_feeling",
                state="overview",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="anger",
                state="moderate",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="calm",
                state="low",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="amusement",
                state="absent",
                certainty="high",
                concept=None,
            ),
        ),
    )


def test_prompt_requires_exact_intensity_unknown_polarity_and_realized_support_checks() -> None:
    mixed = _mixed_context()
    mixed_response = _response(
        "今の気分は、うれしさと腹立たしさもある。",
        (
            "proposition:0:current_feeling",
            "proposition:1:joy",
            "proposition:2:anger",
        ),
    )
    prompt = CharacterRealizationValidatorPromptBuilder().build(mixed, mixed_response)

    assert '"realization_policy": "optional_but_facet_complete_if_realized"' in prompt
    assert '"state_fidelity": "preserve_exact_semantic_state"' in prompt
    assert '"intensity_fidelity": "must_preserve_intensity_if_realized"' in prompt
    assert "state_fidelity=weakened" in prompt
    assert "state_fidelity=unknown_committed" in prompt
    assert "realized_proposition_checks" in prompt
    assert "primaryが正しくても採用済みsupporting propositionが崩れていればreject" in prompt
    assert "presence_only_counterfactual_equivalent" in prompt
    assert "intensity_evidence_spans" in prompt
    assert "単なるpresentへ置き換えても現在のspeechが同じ意味" in prompt

    unknown_prompt = CharacterRealizationValidatorPromptBuilder().build(
        _sadness_unknown_context(certainty="low"),
        _response("はっきりはわからないかな。", ("proposition:0:sadness",)),
    )
    assert '"polarity_commitment": "forbidden"' in unknown_prompt
    assert "yes/no型User Wording Hint" in unknown_prompt


@pytest.mark.asyncio
async def test_acceptance_without_realized_proposition_checks_fails_closed() -> None:
    payload = _accepted_payload([_check("proposition:0:joy")])
    payload.pop("realized_proposition_checks")
    model = _RecordingValidationModel(payload)
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _joy_high_context(),
        _response("すごく楽しいよ。", ("proposition:0:joy",)),
    )

    assert result.accepted is False
    assert result.reason == "realization_validator_schema_invalid"


@pytest.mark.asyncio
async def test_primary_high_weakened_is_rejected_even_when_model_top_level_accepts() -> None:
    model = _RecordingValidationModel(
        _accepted_payload(
            [_check("proposition:0:joy", state_fidelity="weakened")]
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _joy_high_context(),
        _response("うん、楽しいよ。", ("proposition:0:joy",)),
    )

    assert result.accepted is False
    assert result.reason == "semantic_facet_validation_failed"
    assert "proposition:0:joy:state_fidelity:weakened" in result.claim_differences


@pytest.mark.asyncio
async def test_unknown_committed_is_rejected_even_when_model_top_level_accepts() -> None:
    model = _RecordingValidationModel(
        _accepted_payload(
            [_check("proposition:0:sadness", state_fidelity="unknown_committed")]
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _sadness_unknown_context(),
        _response("うん、悲しいよ。", ("proposition:0:sadness",)),
    )

    assert result.accepted is False
    assert result.reason == "semantic_facet_validation_failed"
    assert "proposition:0:sadness:state_fidelity:unknown_committed" in result.claim_differences


@pytest.mark.asyncio
async def test_supporting_weakened_is_rejected_even_when_primary_aggregate_is_true() -> None:
    realizations = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
        "proposition:2:anger",
        "proposition:3:calm",
    )
    model = _RecordingValidationModel(
        _accepted_payload(
            [
                _check("proposition:0:current_feeling"),
                _check("proposition:1:joy", state_fidelity="weakened"),
                _check("proposition:2:anger"),
                _check("proposition:3:calm", state_fidelity="weakened"),
            ]
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _mixed_context(),
        _response(
            "今の気分は、穏やかで、うれしさがありつつ、少し腹立たしさもあります。",
            realizations,
        ),
    )

    assert result.accepted is False
    assert result.reason == "semantic_facet_validation_failed"
    assert "proposition:1:joy:state_fidelity:weakened" in result.claim_differences
    assert "proposition:3:calm:state_fidelity:weakened" in result.claim_differences


@pytest.mark.asyncio
async def test_missing_or_duplicate_realized_check_fails_closed() -> None:
    realizations = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
    )
    missing_model = _RecordingValidationModel(
        _accepted_payload([_check("proposition:0:current_feeling")])
    )
    validator = CharacterRealizationValidator(
        model=missing_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    response = _response("今はかなりうれしい気分。", realizations)

    missing_result = await validator.validate(_source(), _mixed_context(), response)
    assert missing_result.accepted is False
    assert missing_result.reason == "realization_validator_schema_invalid"

    duplicate_model = _RecordingValidationModel(
        _accepted_payload(
            [
                _check("proposition:0:current_feeling"),
                _check("proposition:1:joy"),
                _check("proposition:1:joy"),
            ]
        )
    )
    duplicate_validator = CharacterRealizationValidator(
        model=duplicate_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    duplicate_result = await duplicate_validator.validate(
        _source(), _mixed_context(), response
    )
    assert duplicate_result.accepted is False
    assert duplicate_result.reason == "realization_validator_schema_invalid"


@pytest.mark.asyncio
async def test_unplanned_character_realization_is_rejected_before_model_call() -> None:
    model = _RecordingValidationModel(
        _accepted_payload([_check("proposition:0:joy")])
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _joy_high_context(),
        _response(
            "すごく楽しいし、悲しくもあるよ。",
            ("proposition:0:joy", "proposition:9:sadness"),
        ),
    )

    assert result.accepted is False
    assert result.reason == "unknown_semantic_realization"
    assert result.claim_differences == ("proposition:9:sadness",)
    assert model.activities == []


@pytest.mark.asyncio
async def test_all_realized_proposition_checks_exact_accepts() -> None:
    realizations = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
        "proposition:2:anger",
    )
    model = _RecordingValidationModel(
        _accepted_payload(
            [
                _check("proposition:0:current_feeling"),
                _check(
                    "proposition:1:joy",
                    intensity_evidence_spans=("かなり",),
                ),
                _check(
                    "proposition:2:anger",
                    intensity_evidence_spans=("そこそこ",),
                ),
            ]
        )
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _mixed_context(),
        _response(
            "今の気分は、かなりうれしくて、そこそこ腹立たしさもある。",
            realizations,
        ),
    )

    assert result.accepted is True
    assert result.reason == "semantic_realization_consistent"
