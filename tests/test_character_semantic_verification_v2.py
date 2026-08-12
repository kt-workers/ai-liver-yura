from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.semantic_utterance import SemanticProposition, SemanticUtterancePlan
from app.domain.semantic_validation import (
    CharacterSemanticVerification,
    PropositionSemanticVerification,
)
from app.runtime.character_semantic_verification_policy import (
    CharacterSemanticVerificationPolicy,
)
from app.runtime.semantic_realization_v2_contracts import (
    character_semantic_verification_v2_contract,
    character_utterance_v2_contract,
)


def _plan(proposition: SemanticProposition) -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        propositions=(proposition,),
    )


def _verification(
    proposition_id: str,
    **changes: object,
) -> CharacterSemanticVerification:
    base = PropositionSemanticVerification(
        proposition_id=proposition_id,
        realized=True,
        predicate_relation="preserved",
        value_status_relation="preserved",
        polarity_relation="preserved",
        degree_relation="not_applicable",
        certainty_relation="preserved",
        concept_relation="not_applicable",
        summary_relation="not_applicable",
        evidence_spans=("答え",),
    )
    item = replace(base, **changes)
    return CharacterSemanticVerification(
        propositions=(item,),
        required_content_preserved=True,
        forbidden_additions_absent=True,
        unsupported_new_fact_absent=True,
        existence_boundary_preserved=True,
        budget_preserved=True,
    )


def _decision(
    proposition: SemanticProposition,
    verification: CharacterSemanticVerification,
):
    return CharacterSemanticVerificationPolicy().decide(
        _plan(proposition),
        verification,
        speech="答え",
    )


def test_preserved_absent_proposition_passes() -> None:
    plan = _plan(SemanticProposition("self_state", "anger", state="absent"))
    item_id = plan.propositions[0].proposition_id
    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        _verification(item_id),
        speech="答え",
    )
    assert result.accepted is True


def test_low_degree_weakened_to_bare_presence_rejects_without_surface_dictionary() -> None:
    plan = _plan(SemanticProposition("self_state", "energy", state="low"))
    proposition = plan.propositions[0]
    verification = _verification(
        proposition.proposition_id,
        degree_relation="weaker",
    )

    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        verification,
        speech="答え",
    )

    assert result.accepted is False
    difference = next(item for item in result.differences if item.facet == "degree")
    assert difference.relation == "weaker"
    assert difference.repair == "restore_degree"


def test_degree_strengthening_rejects() -> None:
    plan = _plan(SemanticProposition("self_state", "joy", state="low"))
    proposition = plan.propositions[0]
    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        _verification(proposition.proposition_id, degree_relation="stronger"),
        speech="答え",
    )
    assert result.accepted is False
    assert any(item.facet == "degree" and item.relation == "stronger" for item in result.differences)


def test_unknown_committed_to_specific_polarity_rejects() -> None:
    plan = _plan(
        SemanticProposition(
            "self_state",
            "sadness",
            state="unknown",
            certainty="low",
        )
    )
    proposition = plan.propositions[0]
    verification = _verification(
        proposition.proposition_id,
        value_status_relation="committed_when_unknown",
        polarity_relation="not_applicable",
        certainty_relation="preserved",
    )

    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        verification,
        speech="答え",
    )

    assert result.accepted is False
    assert any(
        item.facet == "value_status" and item.repair == "restore_unknown_status"
        for item in result.differences
    )


def test_medium_certainty_unhedged_stronger_relation_rejects() -> None:
    plan = _plan(
        SemanticProposition(
            "self_state",
            "current_desire",
            state="present",
            certainty="medium",
            concept="curiosity",
        )
    )
    proposition = plan.propositions[0]
    verification = _verification(
        proposition.proposition_id,
        certainty_relation="stronger",
        concept_relation="preserved",
    )

    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        verification,
        speech="答え",
    )

    assert result.accepted is False
    assert any(
        item.facet == "certainty" and item.repair == "reduce_epistemic_commitment"
        for item in result.differences
    )


def test_required_concept_omission_rejects() -> None:
    plan = _plan(
        SemanticProposition(
            "self_state",
            "current_desire",
            state="present",
            certainty="medium",
            concept="connection",
        )
    )
    proposition = plan.propositions[0]
    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        _verification(
            proposition.proposition_id,
            concept_relation="omitted",
        ),
        speech="答え",
    )
    assert result.accepted is False
    assert any(item.facet == "concept" for item in result.differences)


def test_overview_collapse_rejects() -> None:
    plan = _plan(SemanticProposition("self_state", "current_feeling", state="overview"))
    proposition = plan.propositions[0]
    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        _verification(
            proposition.proposition_id,
            polarity_relation="not_applicable",
            summary_relation="collapsed",
        ),
        speech="答え",
    )
    assert result.accepted is False
    assert any(item.facet == "summary" and item.relation == "collapsed" for item in result.differences)


def test_optional_proposition_may_be_fully_omitted() -> None:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        propositions=(
            SemanticProposition("self_state", "current_feeling", state="overview"),
            SemanticProposition("self_state_dimension", "calm", state="moderate"),
        ),
    )
    primary, optional = plan.propositions
    verification = CharacterSemanticVerification(
        propositions=(
            PropositionSemanticVerification(
                primary.proposition_id,
                True,
                "preserved",
                "preserved",
                "not_applicable",
                "not_applicable",
                "preserved",
                "not_applicable",
                "preserved",
                ("答え",),
            ),
            PropositionSemanticVerification(
                optional.proposition_id,
                False,
                "omitted",
                "not_applicable",
                "not_applicable",
                "not_applicable",
                "not_applicable",
                "not_applicable",
                "not_applicable",
                (),
            ),
        ),
        required_content_preserved=True,
        forbidden_additions_absent=True,
        unsupported_new_fact_absent=True,
        existence_boundary_preserved=True,
        budget_preserved=True,
    )

    result = CharacterSemanticVerificationPolicy().decide(plan, verification, speech="答え")
    assert result.accepted is True


def test_optional_realized_but_incomplete_uses_drop_or_restore_repair() -> None:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        propositions=(
            SemanticProposition("self_state", "current_feeling", state="overview"),
            SemanticProposition("self_state_dimension", "calm", state="moderate"),
        ),
    )
    primary, optional = plan.propositions
    verification = CharacterSemanticVerification(
        propositions=(
            PropositionSemanticVerification(
                primary.proposition_id,
                True,
                "preserved",
                "preserved",
                "not_applicable",
                "not_applicable",
                "preserved",
                "not_applicable",
                "preserved",
                ("答え",),
            ),
            PropositionSemanticVerification(
                optional.proposition_id,
                True,
                "preserved",
                "preserved",
                "preserved",
                "weaker",
                "preserved",
                "not_applicable",
                "not_applicable",
                ("答え",),
            ),
        ),
        required_content_preserved=True,
        forbidden_additions_absent=True,
        unsupported_new_fact_absent=True,
        existence_boundary_preserved=True,
        budget_preserved=True,
    )

    result = CharacterSemanticVerificationPolicy().decide(plan, verification, speech="答え")
    assert result.accepted is False
    assert any(
        item.proposition_id == optional.proposition_id
        and item.repair == "restore_facet_or_drop_optional_proposition"
        for item in result.differences
    )


def test_verification_evidence_must_exist_in_speech() -> None:
    plan = _plan(SemanticProposition("self_state", "anger", state="absent"))
    proposition = plan.propositions[0]
    verification = _verification(proposition.proposition_id)
    result = CharacterSemanticVerificationPolicy().decide(
        plan,
        verification,
        speech="別の文",
    )
    assert result.accepted is False
    assert any(item.facet == "evidence" for item in result.differences)


def test_structured_contracts_do_not_expose_llm_accepted_or_reason_authority() -> None:
    verifier_schema = character_semantic_verification_v2_contract().schema
    verifier_properties = verifier_schema["properties"]
    assert isinstance(verifier_properties, dict)
    assert "accepted" not in verifier_properties
    assert "reason" not in verifier_properties
    assert "propositions" in verifier_properties

    character_schema = character_utterance_v2_contract().schema
    character_properties = character_schema["properties"]
    assert isinstance(character_properties, dict)
    assert "realizations" in character_properties
    assert "semantic_realizations" not in character_properties
