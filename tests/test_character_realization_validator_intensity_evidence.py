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
        *,
        observed_state: str,
        state_evidence_spans: list[str],
    ) -> None:
        self.observed_state = observed_state
        self.state_evidence_spans = state_evidence_spans

    async def validate_character_response(self, activity: Activity) -> str:
        if activity.context.get("llm_role") == "character_realization_observer":
            return json.dumps(
                {
                    "observations": [
                        {
                            "realization_id": "proposition:0:joy",
                            "predicate_realized": True,
                            "observed_state": self.observed_state,
                            "observed_certainty": "high",
                            "predicate_evidence_spans": ["楽しい"],
                            "state_evidence_spans": self.state_evidence_spans,
                            "certainty_evidence_spans": [],
                        }
                    ]
                },
                ensure_ascii=False,
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
                "realized_proposition_checks": [
                    {
                        "realization_id": "proposition:0:joy",
                        "predicate_preserved": True,
                        "predicate_evidence_spans": ["楽しい"],
                        "concept_preserved": True,
                        "concept_evidence_spans": [],
                    }
                ],
            },
            ensure_ascii=False,
        )


def _plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
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


def _context() -> ResponseContext:
    plan = _plan()
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


def _validator(
    *,
    observed_state: str,
    state_evidence_spans: list[str],
) -> CharacterRealizationValidator:
    return CharacterRealizationValidator(
        model=_ValidationModel(
            observed_state=observed_state,
            state_evidence_spans=state_evidence_spans,
        ),
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="intensity-evidence-test",
    )


def test_observer_prompt_distinguishes_presence_from_ordered_intensity_without_lexicon() -> None:
    plan = _plan()
    prompt = CharacterRealizationObserverPromptBuilder().build(
        _context(),
        _response("うん、楽しいよ。"),
        plan,
    )

    assert "presentは対象の存在・成立を表す" in prompt
    assert "順序づけられた強度差までは表していない" in prompt
    assert "low/moderate/high/very_highはpresentとは異なり" in prompt
    assert "順序づけられた強度差が意味的に識別できる場合だけ選ぶ" in prompt
    assert "強度の表現手段を特定の単語・副詞・語尾へ固定しない" in prompt


@pytest.mark.asyncio
async def test_e1_presence_only_is_rejected_before_post_observation_validation() -> None:
    result = await _validator(
        observed_state="present",
        state_evidence_spans=["楽しい"],
    ).validate(_source(), _context(), _response("うん、楽しいよ。"))

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_mismatch"
    assert (
        "proposition:0:joy:observed_state_mismatch:expected=high:observed=present"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_observer_fabricated_intensity_evidence_span_is_rejected() -> None:
    result = await _validator(
        observed_state="high",
        state_evidence_spans=["実在しない強度表現"],
    ).validate(_source(), _context(), _response("うん、とても楽しいよ。"))

    assert result.accepted is False
    assert (
        "proposition:0:joy:observer_state_evidence_not_in_speech:実在しない強度表現"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_exact_intensity_with_actual_speech_evidence_can_be_accepted() -> None:
    result = await _validator(
        observed_state="high",
        state_evidence_spans=["とても楽しい"],
    ).validate(_source(), _context(), _response("うん、とても楽しいよ。"))

    assert result.accepted is True
    assert result.reason == "post_observation_semantic_contract_consistent"
