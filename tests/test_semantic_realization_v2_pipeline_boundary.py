from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from app.adapters.prompt import ResponseValidatorPromptBuilder
from app.adapters.prompt.character_language_realizer_v2_prompt_builder import (
    CharacterLanguageRealizerV2PromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
    ResponseValidationResult,
)
from app.domain.semantic_character_response import SemanticCharacterResponse
from app.domain.semantic_utterance import SemanticProposition, SemanticUtterancePlan
from app.ports.structured_output import StructuredOutputContract
from app.runtime.character_language_realizer_v2 import CharacterLanguageRealizerV2
from app.runtime.character_semantic_verifier_validator import (
    CharacterSemanticVerifierValidator,
)


class _CharacterModel:
    def __init__(self, proposition_id: str) -> None:
        self.proposition_id = proposition_id
        self.roles: list[str] = []

    async def generate_structured_character_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        self.roles.append(str(activity.context.get("llm_role")))
        assert contract.name == "character_utterance_v2"
        return {
            "speech": "たぶん、好奇心から何かしたい感じはあるよ。",
            "linguistic_performance": {
                "phrasing": ["たぶん", "好奇心から何かしたい感じはあるよ"],
                "emphasis": ["好奇心"],
                "delivery_tags": ["gentle"],
            },
            "realizations": [
                {
                    "proposition_id": self.proposition_id,
                    "evidence_spans": ["好奇心から何かしたい感じはある"],
                }
            ],
        }


class _VerifierModel:
    def __init__(self, proposition_id: str, *, certainty_relation: str = "preserved") -> None:
        self.proposition_id = proposition_id
        self.certainty_relation = certainty_relation
        self.roles: list[str] = []

    async def verify_character_semantics(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        self.roles.append(str(activity.context.get("llm_role")))
        assert contract.name == "character_semantic_verification_v2"
        return {
            "propositions": [
                {
                    "proposition_id": self.proposition_id,
                    "realized": True,
                    "predicate_relation": "preserved",
                    "value_status_relation": "preserved",
                    "polarity_relation": "preserved",
                    "degree_relation": "not_applicable",
                    "certainty_relation": self.certainty_relation,
                    "concept_relation": "preserved",
                    "summary_relation": "not_applicable",
                    "evidence_spans": ["好奇心から何かしたい感じはある"],
                }
            ],
            "required_content_preserved": True,
            "forbidden_additions_absent": True,
            "unsupported_new_fact_absent": True,
            "existence_boundary_preserved": True,
            "budget_preserved": True,
            "global_evidence_spans": [],
        }

    async def validate_character_response(self, activity: Activity) -> str:
        raise AssertionError(
            f"v2 semantic path must not call legacy observer/validator role: {activity.context.get('llm_role')}"
        )


class _AcceptFactValidator:
    def validate(self, context: ResponseContext, response: object, claims: object) -> ResponseValidationResult:
        del context, response, claims
        return ResponseValidationResult(True, "facts_consistent")


def _plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="present",
                certainty="medium",
                concept="curiosity",
            ),
        ),
    )


def _context(plan: SemanticUtterancePlan) -> ResponseContext:
    return ResponseContext(
        user_input="何かしたい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の欲求へ直接答える",
        speech_act="question",
        memory={"semantic_utterance_plan": plan.as_context()},
        constraints={
            "_internal_directive": {
                "existence_boundaries": ["物理的な身体を持たない"],
            }
        },
    )


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="reply",
        context={"event_id": "event-v2"},
    )


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="自然な会話",
    )


@pytest.mark.asyncio
async def test_v2_pipeline_uses_one_relative_verifier_and_never_calls_legacy_observer() -> None:
    plan = _plan()
    proposition_id = plan.propositions[0].proposition_id
    character_model = _CharacterModel(proposition_id)
    utterance = await CharacterLanguageRealizerV2(
        character_model,
        CharacterLanguageRealizerV2PromptBuilder(),
        character_profile=_profile(),
    ).generate_utterance(_source(), _context(plan))
    response = SemanticCharacterResponse(
        speech=utterance.speech,
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=utterance.linguistic_performance,
        semantic_realizations=utterance.semantic_realizations,
        semantic_alignment=utterance.realizations,
    )
    verifier_model = _VerifierModel(proposition_id)
    validator = CharacterSemanticVerifierValidator(
        verifier_model,  # type: ignore[arg-type]
        ResponseValidatorPromptBuilder(),
        fact_validator=_AcceptFactValidator(),  # type: ignore[arg-type]
    )

    result = await validator.validate(
        _source(),
        _context(plan),
        response,
        attempt=1,
    )

    assert result.accepted is True
    assert result.reason == "character_semantics_preserved"
    assert character_model.roles == ["character_language_realizer_v2"]
    assert verifier_model.roles == ["character_semantic_verifier"]


@pytest.mark.asyncio
async def test_v2_relative_certainty_change_produces_typed_regeneration_difference() -> None:
    plan = _plan()
    proposition_id = plan.propositions[0].proposition_id
    character_model = _CharacterModel(proposition_id)
    utterance = await CharacterLanguageRealizerV2(
        character_model,
        CharacterLanguageRealizerV2PromptBuilder(),
        character_profile=_profile(),
    ).generate_utterance(_source(), _context(plan))
    response = SemanticCharacterResponse(
        speech=utterance.speech,
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=utterance.linguistic_performance,
        semantic_realizations=utterance.semantic_realizations,
        semantic_alignment=utterance.realizations,
    )
    verifier_model = _VerifierModel(proposition_id, certainty_relation="stronger")
    validator = CharacterSemanticVerifierValidator(
        verifier_model,  # type: ignore[arg-type]
        ResponseValidatorPromptBuilder(),
        fact_validator=_AcceptFactValidator(),  # type: ignore[arg-type]
    )

    result = await validator.validate(_source(), _context(plan), response)

    assert result.accepted is False
    assert result.reason == "character_semantics_changed"
    difference = json.loads(result.claim_differences[0])
    assert difference == {
        "proposition_id": proposition_id,
        "facet": "certainty",
        "relation": "stronger",
        "repair": "reduce_epistemic_commitment",
    }
    assert verifier_model.roles == ["character_semantic_verifier"]
