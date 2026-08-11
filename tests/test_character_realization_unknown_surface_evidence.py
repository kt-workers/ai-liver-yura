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
    def __init__(
        self,
        payload: dict[str, object],
        *,
        observed_state: str = "unknown",
        observed_certainty: str = "low",
        state_evidence: str = "はっきりしない",
        certainty_evidence: str = "はっきりしない",
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
                            "certainty_evidence_spans": [self.certainty_evidence],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(self.payload, ensure_ascii=False)


def _context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "sadness"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="sadness",
                state="unknown",
                certainty="low",
                concept=None,
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input="悲しい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の悲しさへ直接答える",
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


def _response(speech: str) -> CharacterResponse:
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(phrasing=(speech,)),
        semantic_realizations=("proposition:0:sadness",),
    )


def _accepted_payload(
    *,
    surface_markers: list[str],
    certainty_evidence: str = "はっきりしない",
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
                "realization_id": "proposition:0:sadness",
                "predicate_preserved": True,
                "predicate_evidence_spans": ["悲し"],
                "state_preserved": True,
                "state_fidelity": "exact",
                "certainty_preserved": True,
                "certainty_evidence_spans": [certainty_evidence],
                "concept_preserved": True,
                "concept_evidence_spans": [],
                "intensity_semantics_preserved": True,
                "presence_only_counterfactual_equivalent": False,
                "intensity_evidence_spans": [],
            }
        ],
        "surface_evidence": {"intensity_markers": surface_markers},
    }


def _validator(
    payload: dict[str, object],
    *,
    observed_state: str = "unknown",
    observed_certainty: str = "low",
    state_evidence: str = "はっきりしない",
    certainty_evidence: str = "はっきりしない",
) -> CharacterRealizationValidator:
    return CharacterRealizationValidator(
        model=_ValidationModel(
            payload,
            observed_state=observed_state,
            observed_certainty=observed_certainty,
            state_evidence=state_evidence,
            certainty_evidence=certainty_evidence,
        ),
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="unknown-surface-evidence-test",
    )


def test_prompt_treats_predicate_uncertainty_as_exact_unknown_candidate() -> None:
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        _response("悲しいかは、今のところはっきりしないよ。"),
    )

    assert "predicate自体を現時点で確定できない" in prompt
    assert "meta-uncertaintyとしてrejectしない" in prompt
    assert "同じ慎重な表現がunknown stateと低い断定度の両方" in prompt
    assert "今のところ" in prompt
    assert "はっきりしない" in prompt
    assert "intensity markerにしない" in prompt


@pytest.mark.asyncio
async def test_model_reported_uncertainty_markers_do_not_reject_valid_unknown() -> None:
    result = await _validator(
        _accepted_payload(surface_markers=["今のところ", "はっきりしない"]),
        state_evidence="はっきりしない",
        certainty_evidence="はっきりしない",
    ).validate(
        _source(),
        _context(),
        _response("今のところ、悲しさはあるかどうか、はっきりしないよ。"),
    )

    assert result.accepted is True
    assert result.reason == "semantic_realization_consistent"
    assert result.claim_differences == ()


@pytest.mark.asyncio
async def test_unknown_committed_to_low_is_rejected_by_independent_observation() -> None:
    result = await _validator(
        _accepted_payload(surface_markers=[], certainty_evidence="かも"),
        observed_state="low",
        observed_certainty="low",
        state_evidence="少し悲しい",
        certainty_evidence="かも",
    ).validate(
        _source(),
        _context(),
        _response("少し悲しいかも。"),
    )

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:sadness:observed_state_mismatch:expected=unknown:observed=low"
        in result.claim_differences
    )
