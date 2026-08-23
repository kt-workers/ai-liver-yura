from __future__ import annotations

from datetime import datetime, timezone

from app.domain.semantic_verification import (
    parse_relation_candidate,
    relation_instructions,
)
from app.domain.semantic_verification.canonical_relation import (
    _canonicalize_relation_value,
)

NOW = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)


def _raw_relation_value() -> dict[str, object]:
    return {
        "candidate_id": "candidate-1",
        "proposition_observations": [
            {
                "proposition_id": "p1",
                "relation": "entailed",
                "polarity_relation": "preserved",
                "certainty_relation": "preserved",
                "degree_relation": "not_applicable",
                "execution_relation": "not_applicable",
            }
        ],
        "blind_unit_accounting": [
            {
                "blind_unit_id": "u1",
                "relation": "supported_by_plan",
                "proposition_ids": ["p1"],
                "evidence_refs": [],
            }
        ],
        "budget_observation": {
            "directed_question_count": 0,
            "new_direction_count": 0,
        },
        "self_disclosure_relation": "within_policy",
    }


def _relation_input() -> dict[str, object]:
    return {
        "pair": {
            "semantic_plan_id": "plan-trusted",
            "utterance_id": "utterance-trusted",
        },
        "blind_observation": {
            "observation_id": "blind-trusted",
            "units": [
                {
                    "unit_id": "u1",
                    "evidence_refs": [
                        {
                            "segment_id": "segment-1",
                            "quote": "ありがとう。",
                            "occurrence_index": 0,
                        }
                    ],
                }
            ],
        },
    }


def test_role_b_instructions_do_not_require_transport_identity_echo() -> None:
    instructions = relation_instructions()

    assert "Role B Providerの出力責務ではありません" in instructions
    assert "Runtimeがtrusted relation requestから決定論的に付与" in instructions
    assert (
        "出力のrequest_id / semantic_plan_id / utterance_id / blind_observation_id"
        not in instructions
    )


def test_runtime_envelope_builds_domain_candidate_from_semantic_only_payload() -> None:
    normalized = _canonicalize_relation_value(
        _raw_relation_value(),
        _relation_input(),
        request_id="relation-request-trusted",
    )
    candidate = parse_relation_candidate(normalized, observed_at=NOW)

    assert candidate.request_id == "relation-request-trusted"
    assert candidate.semantic_plan_id == "plan-trusted"
    assert candidate.utterance_id == "utterance-trusted"
    assert candidate.blind_observation_id == "blind-trusted"
    proposition = candidate.proposition_observations[0]
    assert proposition.supporting_blind_unit_ids == ("u1",)
    assert proposition.evidence_refs[0].quote == "ありがとう。"


def test_runtime_envelope_does_not_trust_provider_identity_values() -> None:
    raw = {
        **_raw_relation_value(),
        "request_id": "provider-wrong-request",
        "semantic_plan_id": "provider-wrong-plan",
        "utterance_id": "provider-wrong-utterance",
        "blind_observation_id": "provider-wrong-blind",
    }

    normalized = _canonicalize_relation_value(
        raw,
        _relation_input(),
        request_id="relation-request-trusted",
    )
    assert isinstance(normalized, dict)
    assert normalized["request_id"] == "relation-request-trusted"
    assert normalized["semantic_plan_id"] == "plan-trusted"
    assert normalized["utterance_id"] == "utterance-trusted"
    assert normalized["blind_observation_id"] == "blind-trusted"
