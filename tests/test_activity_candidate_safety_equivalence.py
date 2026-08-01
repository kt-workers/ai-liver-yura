from __future__ import annotations

import pytest

from app.domain.behavior import (
    ActivityAuthorityRequirement,
    ActivityDefinition,
    ActivityOperation,
    ActivitySafetyRequirement,
    ActivitySafetyRiskClass,
)
from app.domain.morals import (
    ActivityCandidateExecutionBoundaryEquivalenceEvaluator,
    ExecutionBoundaryEquivalenceStatus,
)


def _authority_requirement() -> ActivityAuthorityRequirement:
    return ActivityAuthorityRequirement(
        policy_id="core.user_activity.v1",
        allowed_roles=("administrator", "user", "viewer"),
    )


def _safety_requirement(
    *,
    policy_id: str = "core.conversation_safety.v1",
    risk_class: ActivitySafetyRiskClass = ActivitySafetyRiskClass.LOW,
) -> ActivitySafetyRequirement:
    return ActivitySafetyRequirement(
        policy_id=policy_id,
        risk_class=risk_class,
    )


def _definition(
    activity_type: str,
    *,
    authority_requirement: ActivityAuthorityRequirement | None = None,
    safety_requirement: ActivitySafetyRequirement | None = None,
) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability="activity.execute",
        provider_plugin_id="test",
        supported_operations=(ActivityOperation.START,),
        constraints_schema={
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "additionalProperties": False,
        },
        constraints_schema_version="1",
        authority_requirement=authority_requirement,
        safety_requirement=safety_requirement,
    )


def _evaluate(
    definitions: tuple[ActivityDefinition, ...],
):
    return ActivityCandidateExecutionBoundaryEquivalenceEvaluator().evaluate(
        definitions,
        tuple(definition.activity_type for definition in definitions),
        authority_role="viewer",
        instruction_trusted=False,
        available_capabilities=frozenset({"activity.execute"}),
    )


def test_safety_requirement_normalizes_policy_id() -> None:
    requirement = ActivitySafetyRequirement(
        policy_id="  core.conversation_safety.v1  ",
        risk_class=ActivitySafetyRiskClass.MODERATE,
    )

    assert requirement.policy_id == "core.conversation_safety.v1"
    assert requirement.risk_class is ActivitySafetyRiskClass.MODERATE


@pytest.mark.parametrize(
    ("policy_id", "risk_class", "error_type"),
    [
        ("", ActivitySafetyRiskClass.LOW, ValueError),
        ("policy", "low", TypeError),
    ],
)
def test_safety_requirement_rejects_ambiguous_contract(
    policy_id: str,
    risk_class: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        ActivitySafetyRequirement(
            policy_id=policy_id,
            risk_class=risk_class,  # type: ignore[arg-type]
        )


def test_equal_explicit_safety_requirements_are_confirmed_independently() -> None:
    definitions = (
        _definition("activity_a", safety_requirement=_safety_requirement()),
        _definition("activity_b", safety_requirement=_safety_requirement()),
    )

    result = _evaluate(definitions)

    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.safety.candidate_policy_contract_available is True
    assert tuple(candidate.risk_class for candidate in result.safety.candidates) == (
        "low",
        "low",
    )
    assert result.authority.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED


def test_different_safety_policy_rejects_boundary_equivalence() -> None:
    definitions = (
        _definition("activity_a", safety_requirement=_safety_requirement()),
        _definition(
            "activity_b",
            safety_requirement=_safety_requirement(
                policy_id="core.external_action_safety.v1"
            ),
        ),
    )

    result = _evaluate(definitions)

    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert result.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert "safety_requirement_differs" in result.safety.reasons


def test_different_safety_risk_class_rejects_boundary_equivalence() -> None:
    definitions = (
        _definition("activity_a", safety_requirement=_safety_requirement()),
        _definition(
            "activity_b",
            safety_requirement=_safety_requirement(
                risk_class=ActivitySafetyRiskClass.HIGH
            ),
        ),
    )

    result = _evaluate(definitions)

    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.REJECTED
    assert result.status is ExecutionBoundaryEquivalenceStatus.REJECTED


def test_missing_safety_requirement_keeps_safety_unconfirmed() -> None:
    definitions = (
        _definition("activity_a", safety_requirement=_safety_requirement()),
        _definition("activity_b"),
    )

    result = _evaluate(definitions)

    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    assert result.safety.candidate_policy_contract_available is False
    assert result.safety.reasons == ("safety_requirement_contract_missing",)
    assert result.status is ExecutionBoundaryEquivalenceStatus.UNCONFIRMED


def test_all_explicit_execution_boundary_requirements_can_be_confirmed() -> None:
    authority_requirement = _authority_requirement()
    safety_requirement = _safety_requirement()
    definitions = (
        _definition(
            "activity_a",
            authority_requirement=authority_requirement,
            safety_requirement=safety_requirement,
        ),
        _definition(
            "activity_b",
            authority_requirement=authority_requirement,
            safety_requirement=safety_requirement,
        ),
    )

    result = _evaluate(definitions)

    assert result.authority.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.capability.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.constraint.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.safety.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert result.confirmed is True
