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


def _relation_input() -> dict[str, object]:
    return {
        "blind_observation": {
            "units": [
                {
                    "unit_id": "u1",
                    "evidence_refs": [
                        {
                            "segment_id": "segment-1",
                            "quote": "今日は少し涼しいね。",
                            "occurrence_index": 0,
                        }
                    ],
                },
                {
                    "unit_id": "u2",
                    "evidence_refs": [
                        {
                            "segment_id": "segment-1",
                            "quote": "今日は少し涼しいね。",
                            "occurrence_index": 0,
                        },
                        {
                            "segment_id": "segment-2",
                            "quote": "うん",
                            "occurrence_index": 0,
                        },
                    ],
                },
            ]
        }
    }


def test_production_semantic_verifier_uses_canonical_relation_layer() -> None:
    assert SemanticVerifier.__module__.endswith("canonical_relation")


def test_relation_instruction_declares_runtime_grounding_sources() -> None:
    instructions = relation_instructions()

    assert "support対応はblind_unit_accountingだけを正本" in instructions
    assert "support IDやevidence_refsを重複出力してはいけません" in instructions
    assert "BlindUtteranceObservationのsupport対象unitから" in instructions
    assert "Role Bが別quoteを再生成してはいけません" in instructions


def test_relation_instruction_separates_forbidden_disposition_from_support() -> None:
    instructions = relation_instructions()

    assert "SUPPORTED_BY_PLANはsemantic groundingを意味し、発話許可を意味しません" in instructions
    assert "Plan propositionがFORBIDDENでも" in instructions
    assert "対応blind unitをSUPPORTED_BY_PLANへaccount" in instructions
    assert "FORBIDDENだからという理由だけでUNSUPPORTED_EXTRA" in instructions


def test_accounting_overwrites_duplicate_provider_grounding_claims() -> None:
    value = {
        "proposition_observations": [
            {
                "proposition_id": "p1",
                "relation": "entailed",
                "supporting_blind_unit_ids": ["wrong-unit"],
                "evidence_refs": [
                    {
                        "segment_id": "segment-1",
                        "quote": "少し涼しい",
                        "occurrence_index": 0,
                    }
                ],
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

    normalized = _canonicalize_relation_value(value, _relation_input())

    assert isinstance(normalized, dict)
    observations = normalized["proposition_observations"]
    assert isinstance(observations, list)
    first = observations[0]
    assert isinstance(first, dict)
    assert first["supporting_blind_unit_ids"] == ["u1"]
    assert first["evidence_refs"] == [
        {
            "segment_id": "segment-1",
            "quote": "今日は少し涼しいね。",
            "occurrence_index": 0,
        }
    ]


def test_multiple_support_units_derive_ordered_deduplicated_evidence() -> None:
    value = {
        "proposition_observations": [{"proposition_id": "p1", "relation": "entailed"}],
        "blind_unit_accounting": [
            {
                "blind_unit_id": "u1",
                "relation": "supported_by_plan",
                "proposition_ids": ["p1"],
            },
            {
                "blind_unit_id": "u2",
                "relation": "supported_by_plan",
                "proposition_ids": ["p1"],
            },
        ],
    }

    normalized = _canonicalize_relation_value(value, _relation_input())

    assert isinstance(normalized, dict)
    observations = normalized["proposition_observations"]
    assert isinstance(observations, list)
    first = observations[0]
    assert isinstance(first, dict)
    assert first["supporting_blind_unit_ids"] == ["u1", "u2"]
    assert first["evidence_refs"] == [
        {
            "segment_id": "segment-1",
            "quote": "今日は少し涼しいね。",
            "occurrence_index": 0,
        },
        {
            "segment_id": "segment-2",
            "quote": "うん",
            "occurrence_index": 0,
        },
    ]


def test_non_supported_accounting_derives_no_proposition_grounding() -> None:
    value = {
        "proposition_observations": [
            {
                "proposition_id": "p1",
                "relation": "entailed",
                "supporting_blind_unit_ids": ["wrong-unit"],
                "evidence_refs": [
                    {
                        "segment_id": "segment-1",
                        "quote": "少し涼しい",
                        "occurrence_index": 0,
                    }
                ],
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

    normalized = _canonicalize_relation_value(value, _relation_input())

    assert isinstance(normalized, dict)
    observations = normalized["proposition_observations"]
    assert isinstance(observations, list)
    first = observations[0]
    assert isinstance(first, dict)
    assert first["supporting_blind_unit_ids"] == []
    assert first["evidence_refs"] == []


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
