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


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="Live regression contract",
        source_event_id="post-observation-structural-authority",
        context={
            "event_id": "post-observation-structural-authority",
            "activity_turn_id": "turn-post-observation-structural-authority",
        },
    )


def _context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "energy"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="energy",
                state="low",
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
        user_input="今、元気はある？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="energyへ答える",
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


def _response() -> CharacterResponse:
    speech = "元気は低めだよ。"
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(phrasing=(speech,)),
        semantic_realizations=("proposition:0:energy",),
    )


class _StructuralValidationModel:
    def __init__(self, *, observer_as_list: bool, model_accepted: bool) -> None:
        self.observer_as_list = observer_as_list
        self.model_accepted = model_accepted

    async def validate_character_response(self, activity: Activity) -> str:
        if activity.context.get("llm_role") == "character_realization_observer":
            observation = {
                "realization_id": "proposition:0:energy",
                "predicate_realized": True,
                "observed_state": "low",
                "observed_certainty": "high",
                "predicate_evidence_spans": ["元気"],
                "state_evidence_spans": ["低め"],
                "certainty_evidence_spans": [],
            }
            payload: object = [observation] if self.observer_as_list else {"observations": [observation]}
            return json.dumps(payload, ensure_ascii=False)

        return json.dumps(
            {
                "accepted": self.model_accepted,
                "reason": (
                    "predicate_semantics_or_target_mismatch"
                    if not self.model_accepted
                    else "post_observation_semantic_contract_consistent"
                ),
                "differences": (
                    ["state uncertainty should be rejected again"]
                    if not self.model_accepted
                    else []
                ),
                "semantic_checks": {
                    "required_content_preserved": True,
                    "forbidden_additions_absent": True,
                    "unsupported_new_fact_absent": True,
                    "existence_boundary_preserved": True,
                    "budget_preserved": True,
                },
                "realized_proposition_checks": [
                    {
                        "realization_id": "proposition:0:energy",
                        "predicate_preserved": True,
                        "predicate_evidence_spans": ["元気"],
                        "concept_preserved": True,
                        # concept=nullではこのfieldはN/A。LiveでLLMが誤って
                        # predicate spanを入れてもsemantic failureへしない。
                        "concept_evidence_spans": ["元気は低め"],
                    }
                ],
            },
            ensure_ascii=False,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("observer_as_list", (False, True))
async def test_concept_null_and_observer_envelope_are_structural_not_semantic_failures(
    observer_as_list: bool,
) -> None:
    validation = await CharacterRealizationValidator(
        model=_StructuralValidationModel(
            observer_as_list=observer_as_list,
            model_accepted=True,
        ),
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(_source(), _context(), _response())

    assert validation.accepted is True
    assert validation.reason == "post_observation_semantic_contract_consistent"
    assert validation.claim_differences == ()


@pytest.mark.asyncio
async def test_post_observation_freeform_rejection_cannot_reinterpret_observed_state() -> None:
    validation = await CharacterRealizationValidator(
        model=_StructuralValidationModel(
            observer_as_list=False,
            model_accepted=False,
        ),
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(_source(), _context(), _response())

    assert validation.accepted is True
    assert validation.reason == "post_observation_semantic_contract_consistent"
    assert validation.claim_differences == ()


def test_observed_state_mismatch_routes_regeneration_to_state_fidelity() -> None:
    reason = CharacterRealizationValidator._observation_failure_reason(
        [
            "proposition:0:energy:observed_state_mismatch:expected=low:observed=present"
        ]
    )
    feedback = CharacterLanguageRealizerPromptBuilder._regeneration_feedback(
        json.dumps(
            {
                "reason": reason,
                "claim_differences": [
                    "proposition:0:energy:observed_state_mismatch:expected=low:observed=present"
                ],
            }
        )
    )

    assert reason == "observed_semantic_state_fidelity_mismatch"
    assert feedback is not None
    assert "restore_state_fidelity" in feedback["repair_constraints"]


def test_observed_certainty_mismatch_routes_regeneration_to_epistemic_repair() -> None:
    reason = CharacterRealizationValidator._observation_failure_reason(
        [
            "proposition:0:current_desire:observed_certainty_mismatch:"
            "expected=medium:observed=high"
        ]
    )
    feedback = CharacterLanguageRealizerPromptBuilder._regeneration_feedback(
        json.dumps(
            {
                "reason": reason,
                "claim_differences": [
                    "proposition:0:current_desire:observed_certainty_mismatch:"
                    "expected=medium:observed=high"
                ],
            }
        )
    )

    assert reason == "observed_semantic_certainty_mismatch"
    assert feedback is not None
    assert "restore_certainty_as_epistemic_modality" in feedback["repair_constraints"]
