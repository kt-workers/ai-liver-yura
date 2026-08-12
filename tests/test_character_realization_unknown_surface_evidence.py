from __future__ import annotations

import json

import pytest

from app.adapters.prompt.character_realization_observer_prompt_builder import (
    CharacterRealizationObserverPromptBuilder,
)
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


def _plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
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


def _context() -> ResponseContext:
    plan = _plan()
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


def _accepted_payload() -> dict[str, object]:
    return {
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
                "realization_id": "proposition:0:sadness",
                "predicate_preserved": True,
                "predicate_evidence_spans": ["悲し"],
                "concept_preserved": True,
                "concept_evidence_spans": [],
            }
        ],
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


def test_observer_prompt_treats_predicate_uncertainty_as_unknown_epistemic_state() -> None:
    plan = _plan()
    prompt = CharacterRealizationObserverPromptBuilder().build(
        _context(),
        _response("悲しいかは、今のところはっきりしないよ。"),
        plan,
    )

    assert "unknownは対象の存在・不在・強度・値を現時点で確定していない" in prompt
    assert "特定polarityへcommitしたspeechをunknownにしない" in prompt
    assert "observed_certaintyは、観測器自身の判定自信度でも" in prompt
    assert "このpredicateはobserved_stateである" in prompt
    assert "Semantic Plan側のcertaintyも同じ命題certainty" in prompt
    assert "observed_state=unknownでも同じ定義を使う" in prompt
    assert "unknownだから自動的にcertainty=lowへ固定しない" in prompt


@pytest.mark.asyncio
async def test_valid_unknown_with_explicit_uncertainty_is_accepted_after_observation() -> None:
    result = await _validator(
        _accepted_payload(),
        state_evidence="あるかどうか、はっきりしない",
        certainty_evidence="はっきりしない",
    ).validate(
        _source(),
        _context(),
        _response("今のところ、悲しさはあるかどうか、はっきりしないよ。"),
    )

    assert result.accepted is True
    assert result.reason == "post_observation_semantic_contract_consistent"
    assert result.claim_differences == ()


@pytest.mark.asyncio
async def test_unknown_committed_to_low_is_rejected_by_independent_observation() -> None:
    result = await _validator(
        _accepted_payload(),
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
    assert result.reason == "observed_semantic_state_fidelity_mismatch"
    assert (
        "proposition:0:sadness:observed_state_mismatch:expected=unknown:observed=low"
        in result.claim_differences
    )
