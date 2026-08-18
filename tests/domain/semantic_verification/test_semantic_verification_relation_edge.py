from __future__ import annotations

from datetime import datetime, timezone
from typing import NoReturn, cast

import pytest

from app.domain.semantic_verification import (
    SemanticVerificationContextSnapshot,
    SemanticVerificationError,
    SemanticVerificationFailureCode,
    SemanticVerifier,
    relation_instructions,
)
from app.domain.semantic_verification.canonical_relation import (
    _canonicalize_relation_value,
)


def test_production_semantic_verifier_uses_canonical_relation_layer() -> None:
    assert SemanticVerifier.__module__.endswith("canonical_relation")


def test_relation_instruction_declares_accounting_as_single_support_source() -> None:
    instructions = relation_instructions()

    assert "support対応はblind_unit_accountingだけを正本" in instructions
    assert "同じsupport IDを重複出力してはいけません" in instructions


def test_relation_instruction_separates_forbidden_disposition_from_support() -> None:
    instructions = relation_instructions()

    assert "SUPPORTED_BY_PLANはsemantic groundingを意味し、発話許可を意味しません" in instructions
    assert "Plan propositionがFORBIDDENでも" in instructions
    assert "対応blind unitをSUPPORTED_BY_PLANへaccount" in instructions
    assert "FORBIDDENだからという理由だけでUNSUPPORTED_EXTRA" in instructions


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


@pytest.mark.asyncio
async def test_candidate_value_error_is_structured_schema_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise ValueError("ENTAILED propositionにはevidenceとblind unit supportが必要です")

    legacy_verifier = SemanticVerifier.__mro__[1]
    monkeypatch.setattr(legacy_verifier, "verify", fail)
    verifier = object.__new__(SemanticVerifier)

    with pytest.raises(SemanticVerificationError) as caught:
        await verifier.verify(
            cast(SemanticVerificationContextSnapshot, object()),
            blind_observation_id="blind-observation",
            relation_observation_id="relation-observation",
            semantic_observation_id="semantic-observation",
            acceptance_id="acceptance",
            created_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
        )

    assert caught.value.code is SemanticVerificationFailureCode.SCHEMA_INVALID
    assert "ENTAILED proposition" in str(caught.value)
