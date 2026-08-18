from __future__ import annotations

from app.domain.semantic_verification import SemanticVerifier, relation_instructions
from app.domain.semantic_verification.canonical_relation import (
    _canonicalize_relation_value,
)


def test_production_semantic_verifier_uses_canonical_relation_layer() -> None:
    assert SemanticVerifier.__module__.endswith("canonical_relation")


def test_relation_instruction_declares_accounting_as_single_support_source() -> None:
    instructions = relation_instructions()

    assert "support対応はblind_unit_accountingだけを正本" in instructions
    assert "同じsupport IDを重複出力してはいけません" in instructions


def test_accounting_overwrites_duplicate_provider_support_claim() -> None:
    value = {
        "proposition_observations": [
            {
                "proposition_id": "p1",
                "relation": "entailed",
                "supporting_blind_unit_ids": ["wrong-unit"],
            }
        ],
        "blind_unit_accounting": [
            {
                "blind_unit_id": "u1",
                "relation": "supported_by_plan",
                "proposition_ids": ["p1"],
            }
        ],
    }

    normalized = _canonicalize_relation_value(value)

    assert isinstance(normalized, dict)
    observations = normalized["proposition_observations"]
    assert isinstance(observations, list)
    first = observations[0]
    assert isinstance(first, dict)
    assert first["supporting_blind_unit_ids"] == ["u1"]


def test_non_supported_accounting_derives_no_proposition_support() -> None:
    value = {
        "proposition_observations": [
            {
                "proposition_id": "p1",
                "relation": "entailed",
                "supporting_blind_unit_ids": ["wrong-unit"],
            }
        ],
        "blind_unit_accounting": [
            {
                "blind_unit_id": "u1",
                "relation": "unsupported_extra",
                "proposition_ids": [],
            }
        ],
    }

    normalized = _canonicalize_relation_value(value)

    assert isinstance(normalized, dict)
    observations = normalized["proposition_observations"]
    assert isinstance(observations, list)
    first = observations[0]
    assert isinstance(first, dict)
    assert first["supporting_blind_unit_ids"] == []
