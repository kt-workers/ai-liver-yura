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
            check = self.payload["realized_proposition_checks"][0]
            assert isinstance(check, dict)
            return json.dumps(
                {
                    "observations": [
                        {
                            "realization_id": check["realization_id"],
                            "predicate_realized": True,
                            "observed_state": check.get("observed_state"),
                            "observed_certainty": "high",
                            "predicate_evidence_spans": ["楽しい"],
                            "state_evidence_spans": check.get(
                                "observer_state_evidence_spans", ["楽しい"]
                            ),
                            "certainty_evidence_spans": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(self.payload, ensure_ascii=False)


def _context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "joy"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input="楽しい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の楽しさへ直接答える",
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
        semantic_realizations=("proposition:0:joy",),
    )


def _payload(
    *,
    state_fidelity: str = "exact",
    intensity_semantics_preserved: bool = True,
    presence_only_counterfactual_equivalent: bool = False,
    intensity_evidence_spans: list[str] | None = None,
    observed_state: str = "high",
    observer_state_evidence_spans: list[str] | None = None,
) -> dict[str, object]:
    check: dict[str, object] = {
        "realization_id": "proposition:0:joy",
        "predicate_preserved": True,
        "predicate_evidence_spans": ["楽しい"],
        "state_preserved": True,
        "state_fidelity": state_fidelity,
        "observed_state": observed_state,
        "certainty_preserved": True,
        "certainty_evidence_spans": [],
        "concept_preserved": True,
        "concept_evidence_spans": [],
        "intensity_semantics_preserved": intensity_semantics_preserved,
        "presence_only_counterfactual_equivalent": (
            presence_only_counterfactual_equivalent
        ),
        "intensity_evidence_spans": (
            intensity_evidence_spans
            if intensity_evidence_spans is not None
            else []
        ),
    }
    if observer_state_evidence_spans is not None:
        check["observer_state_evidence_spans"] = observer_state_evidence_spans
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
        "realized_proposition_checks": [check],
        "surface_evidence": {"intensity_markers": []},
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
        source_event_id="intensity-evidence-test",
    )


def test_prompt_requires_presence_counterfactual_and_speech_evidence() -> None:
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        _response("うん、楽しいよ。"),
    )

    assert "単なるpresentへ置き換えても現在のspeechが同じ意味" in prompt
    assert "presence_only_counterfactual_equivalent" in prompt
    assert "intensity_semantics_preserved" in prompt
    assert "intensity_evidence_spans" in prompt
    assert "speechに実在する部分文字列" in prompt


@pytest.mark.asyncio
async def test_e1_presence_only_is_rejected_before_plan_aware_validation() -> None:
    result = await _validator(_payload(observed_state="present")).validate(
        _source(), _context(), _response("うん、楽しいよ。")
    )

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:joy:observed_state_mismatch:expected=high:observed=present"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_presence_only_counterfactual_equivalent_rejects_false_exact() -> None:
    result = await _validator(
        _payload(
            intensity_semantics_preserved=False,
            presence_only_counterfactual_equivalent=True,
            intensity_evidence_spans=["すごく"],
            observer_state_evidence_spans=["すごく"],
        )
    ).validate(_source(), _context(), _response("すごく楽しいよ。"))

    assert result.accepted is False
    assert "proposition:0:joy:intensity_semantics_preserved" in result.claim_differences
    assert (
        "proposition:0:joy:presence_only_counterfactual_equivalent"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_fabricated_intensity_evidence_span_is_rejected() -> None:
    result = await _validator(
        _payload(intensity_evidence_spans=["すごく"])
    ).validate(_source(), _context(), _response("うん、楽しいよ。"))

    assert result.accepted is False
    assert (
        "proposition:0:joy:intensity_evidence_not_in_speech:すごく"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_exact_intensity_with_actual_speech_evidence_can_be_accepted() -> None:
    result = await _validator(
        _payload(
            intensity_evidence_spans=["すごく"],
            observer_state_evidence_spans=["すごく"],
        )
    ).validate(_source(), _context(), _response("うん、すごく楽しいよ。"))

    assert result.accepted is True
    assert result.reason == "semantic_realization_consistent"
