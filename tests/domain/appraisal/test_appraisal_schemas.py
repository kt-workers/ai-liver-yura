from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, ValidationError

from app.domain.appraisal.deep import _candidate_from_json
from app.domain.appraisal.schemas import appraisal_output_schema
from app.domain.contracts.common import JsonValue
from app.domain.llm import StructuredPayload
from tests.domain.appraisal.test_appraisal_paths import NOW, output


def parse(value: dict[str, Any]) -> None:
    frozen = StructuredPayload("candidate", cast(JsonValue, value)).value
    _candidate_from_json(
        frozen,
        source_event_id="event:1",
        source_context_revision=7,
        base_state_revision=0,
        allowed_refs={"event:1"},
        created_at=NOW,
    )


def test_schema_and_parser_compatible() -> None:
    schema = appraisal_output_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(output())
    parse(output())
    assert schema == appraisal_output_schema()
    assert schema is not appraisal_output_schema()


@pytest.mark.parametrize(
    "path,value",
    [
        ("extra", "bad"),
        ("dimensions.0.extra", "bad"),
        ("proposals.0.extra", "bad"),
        ("dimensions.0.kind", "unknown"),
        ("proposals.0.facet_kind", "unknown"),
        ("dimensions.0.value", 2),
        ("proposals.0.delta", 2),
        ("proposals.0.confidence", -1),
        ("salience", 2),
        ("relevance", -1),
    ],
)
def test_schema_rejects_shape_enum_and_range(path: str, value: object) -> None:
    data = output()
    node: Any = data
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    node[keys[-1]] = value
    with pytest.raises(ValidationError):
        Draft202012Validator(appraisal_output_schema()).validate(data)


@pytest.mark.parametrize("case", ["identifier", "duplicate", "target", "zero", "unbounded"])
def test_schema_success_does_not_replace_domain_validation(case: str) -> None:
    data = output()
    if case == "identifier":
        data["candidate_id"] = ""
    elif case == "duplicate":
        data["evidence_refs"] = ["event:1", "event:1"]
    elif case == "target":
        data["proposals"][0]["facet_kind"] = "interest"
    elif case == "zero":
        data["proposals"][0]["delta"] = 0
    else:
        data["proposals"][0]["cause_refs"] = ["outside"]
    Draft202012Validator(appraisal_output_schema()).validate(data)
    with pytest.raises(ValueError):
        parse(data)
