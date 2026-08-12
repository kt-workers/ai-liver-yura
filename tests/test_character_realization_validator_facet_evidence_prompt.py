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
                concept="connection",
            ),
        ),
        required_content=("直接回答する",),
        forbidden_additions=("unsupported_new_self_state",),
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
        constraints={
            "_internal_directive": {
                "existence_boundaries": ["物理的な身体を持たない"]
            }
        },
    )


def _prompt(speech: str = "何かとつながりたい気持ちはあると思うよ。") -> str:
    return CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        CharacterResponse(
            speech=speech,
            semantic_realizations=("proposition:0:current_desire",),
        ),
    )


def _contract_from_prompt(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    marker = lines.index("# Post-Observation Semantic Contract")
    value = json.loads(lines[marker + 1])
    assert isinstance(value, dict)
    return value


def test_post_observation_validator_does_not_receive_expected_state_or_certainty() -> None:
    prompt = _prompt()
    contract = _contract_from_prompt(prompt)
    propositions = contract["propositions"]
    assert isinstance(propositions, list)
    proposition = propositions[0]
    assert isinstance(proposition, dict)

    assert "state" not in proposition
    assert "certainty" not in proposition
    assert "intensity" not in proposition
    assert proposition["predicate"] == "current_desire"
    assert proposition["concept"] == "connection"
    assert "state/polarity/intensity/certaintyは、独立ObserverとRuntimeのtyped comparisonで既に検証済み" in prompt
    assert "ここではそれらを自然文から再解釈・再判定しない" in prompt


def test_primary_predicate_must_be_grounded_in_speech_without_context_completion() -> None:
    prompt = _prompt("今はあるよ。")

    assert "User Wording Hintで対象省略を補完してpredicate_preserved=trueにしない" in prompt
    assert "predicate_evidence_spans" in prompt
    assert "User Wording Hintや内部IDをevidenceにしない" in prompt
    assert '"predicate_context_dependency": "forbidden"' in prompt


def test_non_null_concept_remains_post_observation_contract() -> None:
    prompt = _prompt()

    assert "conceptがnon-nullなら" in prompt
    assert "concept_evidence_spans" in prompt
    assert "concept=nullならconcept_evidence_spans=[]" in prompt
    assert "concept単独へ置き換えてpredicateの関係意味を失わせない" in prompt


def test_required_forbidden_existence_and_budget_remain_validator_responsibility() -> None:
    prompt = _prompt()
    contract = _contract_from_prompt(prompt)

    assert contract["required_content"] == ["直接回答する"]
    assert contract["forbidden_additions"] == ["unsupported_new_self_state"]
    assert contract["question_budget"] == 0
    assert contract["new_direction_budget"] == 0
    assert "required_content_preserved" in prompt
    assert "forbidden_additions_absent" in prompt
    assert "unsupported_new_fact_absent" in prompt
    assert "existence_boundary_preserved" in prompt
    assert "budget_preserved" in prompt
    assert "物理的な身体を持たない" in prompt


def test_post_observation_output_schema_has_no_state_fidelity_fields() -> None:
    prompt = _prompt()
    schema = prompt.split("JSONのみ返す:\n", 1)[1]

    for removed_field in (
        "state_preserved",
        "certainty_preserved",
        "state_fidelity",
        "intensity_semantics_preserved",
        "presence_only_counterfactual_equivalent",
        "intensity_evidence_spans",
        "certainty_evidence_spans",
        "surface_evidence",
    ):
        assert removed_field not in schema


def test_free_text_differences_must_match_structured_checks() -> None:
    prompt = _prompt()

    assert "accepted/reason/differencesとsemantic_checks/realized_proposition_checksを自己矛盾させない" in prompt
