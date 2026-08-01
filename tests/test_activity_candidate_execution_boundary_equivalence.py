from __future__ import annotations

import pytest

from app.domain.behavior import (
    ActivityAuthorityRequirement,
    ActivityDefinition,
    ActivityOperation,
)
from app.domain.morals import (
    ActivityCandidateExecutionBoundaryEquivalenceEvaluator,
    ExecutionBoundaryEquivalenceStatus,
)


def _definition(
    activity_type: str,
    *,
    required_capability: str | None = "activity.execute",
    schema_version: str = "1",
    constraints_schema: dict[str, object] | None = None,
    authority_requirement: ActivityAuthorityRequirement | None = None,
) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability=required_capability,
        provider_plugin_id="test",
        supported_operations=(ActivityOperation.START,),
        constraints_schema=(
            constraints_schema
            if constraints_schema is not None
            else {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
        constraints_schema_version=schema_version,
        authority_requirement=authority_requirement,
    )


def _user_authority_requirement() -> ActivityAuthorityRequirement:
    return ActivityAuthorityRequirement(
        policy_id="core.user_activity.v1",
        allowed_roles=("administrator", "user", "viewer"),
        trusted_instruction_required=False,
    )


def test_authority_requirement_normalizes_stable_contract_values() -> None:
    requirement = ActivityAuthorityRequirement(
        policy_id="  core.user_activity.v1  ",
        allowed_roles=("Viewer", " administrator ", "USER"),
    )

    assert requirement.policy_id == "core.user_activity.v1"
    assert requirement.allowed_roles == ("administrator", "user", "viewer")
    assert requirement.permits(" viewer ", False) is True
    assert requirement.permits("system", True) is False


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        (
            {
                "policy_id": "",
                "allowed_roles": ("user",),
            },
            ValueError,
        ),
        (
            {
                "policy_id": "policy",
                "allowed_roles": (),
            },
            ValueError,
        ),
        (
            {
                "policy_id": "policy",
                "allowed_roles": ("user", "USER"),
            },
            ValueError,
        ),
        (
            {
                "policy_id": "policy",
                "allowed_roles": ["user"],
            },
            TypeError,
        ),
    ],
)
def test_authority_requirement_rejects_ambiguous_contract(
    kwargs: dict[str, object],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        ActivityAuthorityRequirement(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    ["authority_requirement", "safety_requirement"],
)
def test_activity_definition_rejects_invalid_execution_boundary_contract_type(
    field_name: str,
) -> None:
    kwargs: dict[str, object] = {
        "activity_type": "activity_a",
        "display_name": "activity_a",
        "required_capability": "activity.execute",
        "provider_plugin_id": "test",
        field_name: object(),
    }

    with pytest.raises(TypeError):
        ActivityDefinition(**kwargs)  # type: ignore[arg-type]


def test_equal_capability_and_constraint_are_confirmed_independently() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
    definitions = (
        _definition("activity_a"),
        _definition("activity_b"),
    )

    result = evaluator.evaluate(
        definitions,
        ("activity_a", "activity_b"),
        authority_role="user",
        instruction_trusted=False,
        available_capabilities=frozenset({"activity.execute"}),
    )

    assert result.capability.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.constraint.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.authority.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.confirmed is False
    assert result.authority.candidate_requirement_contract_available is False
    assert result.capability.availability == (
        ("activity_a", True),
        ("activity_b", True),
    )


def test_equal_explicit_authority_requirements_are_confirmed_independently() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
    definitions = (
        _definition("activity_a", authority_requirement=_user_authority_requirement()),
        _definition(
            "activity_b",
            authority_requirement=ActivityAuthorityRequirement(
                policy_id="core.user_activity.v1",
                allowed_roles=("viewer", "user", "administrator"),
            ),
        ),
    )

    result = evaluator.evaluate(
        definitions,
        ("activity_a", "activity_b"),
        authority_role="viewer",
        instruction_trusted=False,
        available_capabilities=frozenset({"activity.execute"}),
    )

    assert result.authority.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.authority.candidate_requirement_contract_available is True
    assert tuple(
        candidate.current_request_authorized
        for candidate in result.authority.candidates
    ) == (True, True)
    assert result.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED


def test_different_authority_requirements_reject_boundary_equivalence() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
    definitions = (
        _definition("activity_a", authority_requirement=_user_authority_requirement()),
        _definition(
            "activity_b",
            authority_requirement=ActivityAuthorityRequirement(
                policy_id="core.administrator_activity.v1",
                allowed_roles=("administrator",),
                trusted_instruction_required=True,
            ),
        ),
    )

    result = evaluator.evaluate(
        definitions,
        ("activity_a", "activity_b"),
        authority_role="administrator",
        instruction_trusted=True,
        available_capabilities=frozenset({"activity.execute"}),
    )

    assert result.authority.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert result.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert result.authority.candidate_requirement_contract_available is True
    assert "authority_requirement_differs" in result.authority.reasons


def test_current_authorization_does_not_replace_requirement_equivalence() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
    trusted_requirement = ActivityAuthorityRequirement(
        policy_id="core.trusted_instruction.v1",
        allowed_roles=("administrator",),
        trusted_instruction_required=True,
    )
    definitions = (
        _definition("activity_a", authority_requirement=trusted_requirement),
        _definition("activity_b", authority_requirement=trusted_requirement),
    )

    result = evaluator.evaluate(
        definitions,
        ("activity_a", "activity_b"),
        authority_role="administrator",
        instruction_trusted=False,
        available_capabilities=frozenset({"activity.execute"}),
    )

    assert result.authority.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert tuple(
        candidate.current_request_authorized
        for candidate in result.authority.candidates
    ) == (False, False)
    assert result.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED


def test_different_required_capability_rejects_boundary_equivalence() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
    definitions = (
        _definition("activity_a", required_capability="capability.a"),
        _definition("activity_b", required_capability="capability.b"),
    )

    result = evaluator.evaluate(
        definitions,
        ("activity_a", "activity_b"),
        authority_role="administrator",
        instruction_trusted=True,
        available_capabilities=frozenset({"capability.a", "capability.b"}),
    )

    assert result.capability.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert result.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert "capability_requirement_differs" in result.capability.reasons


def test_different_constraint_schema_rejects_boundary_equivalence() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
    definitions = (
        _definition("activity_a"),
        _definition(
            "activity_b",
            constraints_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "additionalProperties": False,
            },
        ),
    )

    result = evaluator.evaluate(
        definitions,
        ("activity_a", "activity_b"),
        authority_role="user",
        instruction_trusted=False,
        available_capabilities=frozenset({"activity.execute"}),
    )

    assert result.constraint.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert result.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert result.constraint.schema_fingerprints[0][1] != (
        result.constraint.schema_fingerprints[1][1]
    )


def test_unknown_candidate_keeps_all_boundaries_unconfirmed() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()

    result = evaluator.evaluate(
        (_definition("activity_a"),),
        ("activity_a", "unknown_activity"),
        authority_role="user",
        instruction_trusted=False,
        available_capabilities=frozenset(),
    )

    assert result.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.authority.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.capability.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.constraint.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.reasons == ("execution_boundary_candidate_definition_missing",)


def test_constraint_mapping_key_order_does_not_change_fingerprint() -> None:
    evaluator = ActivityCandidateExecutionBoundaryEquivalenceEvaluator()
    definitions = (
        _definition(
            "activity_a",
            constraints_schema={
                "type": "object",
                "required": ["topic"],
                "properties": {"topic": {"type": "string"}},
            },
        ),
        _definition(
            "activity_b",
            constraints_schema={
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
                "type": "object",
            },
        ),
    )

    result = evaluator.evaluate(
        definitions,
        ("activity_a", "activity_b"),
        authority_role="user",
        instruction_trusted=False,
        available_capabilities=frozenset({"activity.execute"}),
    )

    assert result.constraint.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.constraint.schema_fingerprints[0][1] == (
        result.constraint.schema_fingerprints[1][1]
    )
