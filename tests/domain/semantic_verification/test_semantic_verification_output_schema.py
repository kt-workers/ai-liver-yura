from __future__ import annotations

import pytest
from jsonschema import ValidationError, validate

from app.domain.semantic_verification import relation_output_schema


def _payload(*, relation: str, proposition_ids: list[str]) -> dict[str, object]:
    return {
        "candidate_id": "candidate-1",
        "request_id": "request-1",
        "semantic_plan_id": "plan-1",
        "utterance_id": "utterance-1",
        "blind_observation_id": "blind-1",
        "proposition_observations": [
            {
                "proposition_id": "p1",
                "relation": "entailed",
                "polarity_relation": "preserved",
                "certainty_relation": "preserved",
                "degree_relation": "not_applicable",
                "execution_relation": "not_applicable",
                "evidence_refs": [],
                "supporting_blind_unit_ids": ["u1"],
            }
        ],
        "blind_unit_accounting": [
            {
                "blind_unit_id": "u1",
                "relation": relation,
                "proposition_ids": proposition_ids,
                "evidence_refs": [],
            }
        ],
        "budget_observation": {
            "directed_question_count": 0,
            "new_direction_count": 0,
        },
        "self_disclosure_relation": "within_policy",
    }


def test_supported_by_plan_requires_proposition_reference() -> None:
    schema = relation_output_schema()

    validate(_payload(relation="supported_by_plan", proposition_ids=["p1"]), schema)
    with pytest.raises(ValidationError):
        validate(_payload(relation="supported_by_plan", proposition_ids=[]), schema)


@pytest.mark.parametrize(
    "relation",
    ["unsupported_extra", "permitted_non_material_style", "ambiguous"],
)
def test_non_supported_accounting_forbids_proposition_reference(relation: str) -> None:
    schema = relation_output_schema()

    validate(_payload(relation=relation, proposition_ids=[]), schema)
    with pytest.raises(ValidationError):
        validate(_payload(relation=relation, proposition_ids=["p1"]), schema)
