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


class _ValidationModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def validate_character_response(self, activity: Activity) -> str:
        if activity.context.get("llm_role") == "character_realization_observer":
            observations = self.payload.get("_observer_observations")
            return json.dumps({"observations": observations}, ensure_ascii=False)
        comparison = {
            key: value
            for key, value in self.payload.items()
            if key != "_observer_observations"
        }
        return json.dumps(comparison, ensure_ascii=False)


def _context(
    *,
    predicate: str = "energy",
    state: str = "low",
    certainty: str = "high",
    concept: str | None = None,
) -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", predicate),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate=predicate,
                state=state,
                certainty=certainty,
                concept=concept,
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input="今どう？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の内部状態へ直接答える",
        speech_act="question",
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )


def _response(predicate: str, speech: str) -> CharacterResponse:
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(phrasing=(speech,)),
        semantic_realizations=(f"proposition:0:{predicate}",),
    )


def _payload(
    predicate: str,
    *,
    predicate_spans: list[str] | None = None,
    concept_spans: list[str] | None = None,
    observer_state: str | None = "absent",
    observer_certainty: str = "high",
    observer_predicate_spans: list[str] | None = None,
    observer_state_spans: list[str] | None = None,
    observer_certainty_spans: list[str] | None = None,
) -> dict[str, object]:
    comparison_predicate_spans = predicate_spans or []
    observation_predicate_spans = (
        observer_predicate_spans
        if observer_predicate_spans is not None
        else comparison_predicate_spans
    )
    observation_state_spans = (
        observer_state_spans
        if observer_state_spans is not None
        else observation_predicate_spans
    )
    return {
        "_observer_observations": [
            {
                "realization_id": f"proposition:0:{predicate}",
                "predicate_realized": True,
                "observed_state": observer_state,
                "observed_certainty": observer_certainty,
                "predicate_evidence_spans": observation_predicate_spans,
                "state_evidence_spans": observation_state_spans,
                "certainty_evidence_spans": observer_certainty_spans or [],
            }
        ],
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
                "realization_id": f"proposition:0:{predicate}",
                "predicate_preserved": True,
                "predicate_evidence_spans": comparison_predicate_spans,
                "concept_preserved": True,
                "concept_evidence_spans": concept_spans or [],
            }
        ],
    }


def _validator(payload: dict[str, object]) -> CharacterRealizationValidator:
    return CharacterRealizationValidator(
        model=_ValidationModel(payload),
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="facet-evidence-runtime-gate",
    )


@pytest.mark.asyncio
async def test_accepted_payload_missing_post_observation_evidence_field_fails_closed() -> None:
    payload = _payload(
        "joy",
        predicate_spans=["楽しい気持ち"],
    )
    check = payload["realized_proposition_checks"][0]
    assert isinstance(check, dict)
    del check["concept_evidence_spans"]

    result = await _validator(payload).validate(
        _source(),
        _context(predicate="joy", state="absent"),
        _response("joy", "楽しい気持ちはないよ。"),
    )

    assert result.accepted is False
    assert result.reason == "realization_validator_schema_invalid"


@pytest.mark.asyncio
async def test_post_observation_predicate_evidence_must_exist_in_speech() -> None:
    result = await _validator(
        _payload(
            "joy",
            predicate_spans=["楽しい気分"],
            observer_predicate_spans=["楽しい気持ち"],
            observer_state_spans=["楽しい気持ちはない"],
        )
    ).validate(
        _source(),
        _context(predicate="joy", state="absent"),
        _response("joy", "楽しい気持ちはないよ。"),
    )

    assert result.accepted is False
    assert (
        "proposition:0:joy:predicate_evidence_not_in_speech:楽しい気分"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_medium_certainty_requires_observer_speech_evidence() -> None:
    result = await _validator(
        _payload(
            "current_desire",
            predicate_spans=["したい気持ちはある"],
            observer_state="present",
            observer_certainty="medium",
            observer_state_spans=["したい気持ちはある"],
            observer_certainty_spans=[],
        )
    ).validate(
        _source(),
        _context(
            predicate="current_desire",
            state="present",
            certainty="medium",
        ),
        _response("current_desire", "たぶん、したい気持ちはあるよ。"),
    )

    assert result.accepted is False
    assert (
        "proposition:0:current_desire:observer_certainty_evidence_missing"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_non_null_concept_requires_post_observation_speech_evidence() -> None:
    result = await _validator(
        _payload(
            "current_desire",
            predicate_spans=["知りたい気持ちはある"],
            observer_state="present",
            observer_certainty="medium",
            observer_state_spans=["知りたい気持ちはある"],
            observer_certainty_spans=["たぶん"],
        )
    ).validate(
        _source(),
        _context(
            predicate="current_desire",
            state="present",
            certainty="medium",
            concept="curiosity",
        ),
        _response("current_desire", "たぶん、知りたい気持ちはあるよ。"),
    )

    assert result.accepted is False
    assert (
        "proposition:0:current_desire:concept_evidence_missing"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_null_concept_treats_model_concept_evidence_as_non_authoritative_na() -> None:
    result = await _validator(
        _payload(
            "joy",
            predicate_spans=["楽しい気持ち"],
            concept_spans=["楽しい"],
        )
    ).validate(
        _source(),
        _context(predicate="joy", state="absent"),
        _response("joy", "楽しい気持ちはないよ。"),
    )

    assert result.accepted is True
    assert result.reason == "post_observation_semantic_contract_consistent"
    assert result.claim_differences == ()


@pytest.mark.asyncio
async def test_e8_bare_presence_is_rejected_by_independent_observation() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気はある"],
            observer_state="present",
            observer_state_spans=["元気はある"],
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "うん、元気はあるよ。"),
    )

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_fidelity_mismatch"
    assert (
        "proposition:0:energy:observed_state_mismatch:expected=low:observed=present"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_unlisted_paraphrase_can_preserve_low_without_runtime_dictionary() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気はそれなりに残ってる"],
            observer_state="low",
            observer_state_spans=["それなりに残ってる"],
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "元気はそれなりに残ってるよ。"),
    )

    assert result.accepted is True
    assert result.reason == "post_observation_semantic_contract_consistent"


@pytest.mark.asyncio
async def test_degree_suffix_can_be_observed_semantically_without_runtime_dictionary() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気は低め"],
            observer_state="low",
            observer_state_spans=["低め"],
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "元気は低めだよ。"),
    )

    assert result.accepted is True


@pytest.mark.asyncio
async def test_observer_missing_typed_state_fails_closed() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気は控えめ"],
            observer_state=None,
            observer_state_spans=["控えめ"],
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "元気は控えめだよ。"),
    )

    assert result.accepted is False
    assert result.reason == "realization_observer_schema_invalid"


@pytest.mark.asyncio
async def test_observer_state_evidence_must_exist_in_speech() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気"],
            observer_state="low",
            observer_predicate_spans=["元気"],
            observer_state_spans=["存在しない強度表現"],
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "元気は控えめだよ。"),
    )

    assert result.accepted is False
    assert (
        "proposition:0:energy:observer_state_evidence_not_in_speech:存在しない強度表現"
        in result.claim_differences
    )
