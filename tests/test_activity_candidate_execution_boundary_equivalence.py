from __future__ import annotations

from app.domain.behavior import ActivityDefinition, ActivityOperation
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
    )


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
    assert result.capability.availability == (
        ("activity_a", True),
        ("activity_b", True),
    )


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
