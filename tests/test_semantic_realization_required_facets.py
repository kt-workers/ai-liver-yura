from __future__ import annotations

import json

from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
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


def _context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="present",
                certainty="medium",
                concept="curiosity",
                evidence_refs=("response_content_plan.primary_desire",),
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
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
    return CharacterResponse(
        speech="うん、少しあるよ。",
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(
            phrasing=("うん", "少しあるよ"),
            emphasis=("少し",),
            delivery_tags=("gentle",),
        ),
        semantic_realizations=("proposition:0:current_desire",),
    )


def _json_section(prompt: str, heading: str, next_heading: str) -> dict[str, object]:
    section = prompt.split(f"{heading}\n", 1)[1].split(f"\n{next_heading}", 1)[0]
    value = json.loads(section)
    assert isinstance(value, dict)
    return value


def _output_schema_example(prompt: str) -> dict[str, object]:
    value = json.loads(prompt.rsplit("JSONのみ返す:\n", 1)[1])
    assert isinstance(value, dict)
    return value


def test_validator_marks_primary_predicate_state_certainty_and_non_null_concept_as_required_facets() -> None:
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        _response(),
    )

    semantic_view = _json_section(
        prompt,
        "# Semantic Utterance Plan",
        "# User Wording Hint",
    )
    propositions = semantic_view["propositions"]
    assert isinstance(propositions, list)
    primary = propositions[0]
    assert isinstance(primary, dict)

    assert primary["required"] is True
    assert primary["predicate"] == "current_desire"
    assert primary["state"] == "present"
    assert primary["certainty"] == "medium"
    assert primary["concept"] == "curiosity"
    assert primary["required_facets"] == ["predicate", "state", "certainty", "concept"]
    assert primary["if_realized_required_facets"] == [
        "predicate",
        "state",
        "certainty",
        "concept",
    ]
    assert primary["state_semantics"] == "presence_without_intensity"
    assert primary["certainty_surface_requirement"] == "overt_epistemic_modality"
    assert "response_content_plan.primary_desire" not in prompt

    output_schema = _output_schema_example(prompt)
    semantic_checks = output_schema["semantic_checks"]
    assert isinstance(semantic_checks, dict)
    assert "required_facets_preserved" in semantic_checks
    assert "predicate_preserved" in semantic_checks
    assert "state_preserved" in semantic_checks
    assert "certainty_preserved" in semantic_checks
    assert "concept_preserved" in semantic_checks
    assert "unsupported_intensity_added" in semantic_checks


def test_semantic_realization_id_requires_per_proposition_facet_validation() -> None:
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        _response(),
    )

    utterance_view = _json_section(
        prompt,
        "# Character Utterance",
        "# Existence Boundaries",
    )
    assert utterance_view["semantic_realizations"] == [
        "proposition:0:current_desire"
    ]

    output_schema = _output_schema_example(prompt)
    proposition_checks = output_schema["realized_proposition_checks"]
    assert isinstance(proposition_checks, list)
    check = proposition_checks[0]
    assert isinstance(check, dict)
    assert check["state_fidelity"] == "exact"
    assert "predicate_preserved" in check
    assert "state_preserved" in check
    assert "certainty_preserved" in check
    assert "concept_preserved" in check
    assert "predicate_evidence_spans" in check
    assert "certainty_evidence_spans" in check
    assert "concept_evidence_spans" in check
    assert "intensity_evidence_spans" in check
