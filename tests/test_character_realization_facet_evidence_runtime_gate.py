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
            checks = self.payload.get("realized_proposition_checks", [])
            observations: list[dict[str, object]] = []
            if isinstance(checks, list):
                for check in checks:
                    if not isinstance(check, dict):
                        continue
                    predicate_spans = check.get("predicate_evidence_spans", [])
                    intensity_spans = check.get("intensity_evidence_spans", [])
                    certainty_spans = check.get("certainty_evidence_spans", [])
                    observations.append(
                        {
                            "realization_id": check.get("realization_id"),
                            "predicate_realized": check.get("predicate_preserved", True),
                            "observed_state": check.get("observed_state"),
                            "observed_certainty": check.get("observed_certainty", "high"),
                            "predicate_evidence_spans": predicate_spans,
                            "state_evidence_spans": (
                                intensity_spans if intensity_spans else predicate_spans
                            ),
                            "certainty_evidence_spans": certainty_spans,
                        }
                    )
            return json.dumps({"observations": observations}, ensure_ascii=False)
        return json.dumps(self.payload, ensure_ascii=False)


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
    certainty_spans: list[str] | None = None,
    concept_spans: list[str] | None = None,
    intensity_spans: list[str] | None = None,
    surface_markers: list[str] | None = None,
    observed_state: str | None = None,
    observed_certainty: str = "high",
) -> dict[str, object]:
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
                "realization_id": f"proposition:0:{predicate}",
                "predicate_preserved": True,
                "predicate_evidence_spans": predicate_spans or [],
                "state_preserved": True,
                "state_fidelity": "exact",
                "observed_state": observed_state,
                "observed_certainty": observed_certainty,
                "certainty_preserved": True,
                "certainty_evidence_spans": certainty_spans or [],
                "concept_preserved": True,
                "concept_evidence_spans": concept_spans or [],
                "intensity_semantics_preserved": True,
                "presence_only_counterfactual_equivalent": False,
                "intensity_evidence_spans": intensity_spans or [],
            }
        ],
        "surface_evidence": {"intensity_markers": surface_markers or []},
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
async def test_accepted_payload_missing_facet_evidence_field_fails_closed() -> None:
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
async def test_predicate_evidence_must_exist_in_speech() -> None:
    result = await _validator(
        _payload("joy", predicate_spans=["楽しい気分"])
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
async def test_medium_certainty_requires_speech_evidence() -> None:
    result = await _validator(
        _payload("current_desire", predicate_spans=["したい気持ちはある"])
    ).validate(
        _source(),
        _context(
            predicate="current_desire",
            state="present",
            certainty="medium",
        ),
        _response("current_desire", "したい気持ちはあるよ。"),
    )

    assert result.accepted is False
    assert (
        "proposition:0:current_desire:certainty_evidence_missing"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_non_null_concept_requires_speech_evidence() -> None:
    result = await _validator(
        _payload(
            "current_desire",
            predicate_spans=["知りたい気持ちはある"],
            certainty_spans=["たぶん"],
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
async def test_null_concept_rejects_unexpected_concept_evidence() -> None:
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

    assert result.accepted is False
    assert "proposition:0:joy:unexpected_concept_evidence" in result.claim_differences


@pytest.mark.asyncio
async def test_e8_bare_presence_is_rejected_by_independent_observation() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気はある"],
            intensity_spans=["元気はある"],
            observed_state="present",
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "うん、元気はあるよ。"),
    )

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_mismatch"
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
            intensity_spans=["それなりに"],
            surface_markers=["それなりに"],
            observed_state="low",
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "元気はそれなりに残ってるよ。"),
    )

    assert result.accepted is True
    assert result.reason == "semantic_realization_consistent"


@pytest.mark.asyncio
async def test_degree_suffix_can_be_observed_semantically_without_runtime_dictionary() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気は低め"],
            intensity_spans=["低め"],
            surface_markers=["低め"],
            observed_state="low",
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
            intensity_spans=["控えめ"],
            observed_state=None,
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "元気は控えめだよ。"),
    )

    assert result.accepted is False
    assert result.reason == "realization_observer_schema_invalid"


@pytest.mark.asyncio
async def test_surface_intensity_marker_must_exist_in_speech() -> None:
    result = await _validator(
        _payload(
            "energy",
            predicate_spans=["元気は少しある"],
            intensity_spans=["少し"],
            surface_markers=["かなり"],
            observed_state="low",
        )
    ).validate(
        _source(),
        _context(predicate="energy", state="low"),
        _response("energy", "元気は少しあるよ。"),
    )

    assert result.accepted is False
    assert (
        "surface_intensity_marker_not_in_speech:かなり"
        in result.claim_differences
    )
