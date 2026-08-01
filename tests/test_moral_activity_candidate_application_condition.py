from __future__ import annotations

from app.domain.morals import (
    ActivityCandidateExecutionBoundaryEquivalenceAssessment,
    ActivityCandidateSemanticEquivalenceAssessment,
    ExecutionBoundaryEquivalenceStatus,
    MoralActivityCandidateApplicationConditionEvaluator,
    MoralActivityCandidateApplicationConditionStatus,
    SemanticEquivalenceStatus,
)


CANDIDATE_GROUP = (
    "autonomous_talk",
    "conversation_with_user",
)


def _semantic(
    status: SemanticEquivalenceStatus,
    *,
    candidate_group: tuple[str, ...] = CANDIDATE_GROUP,
) -> ActivityCandidateSemanticEquivalenceAssessment:
    return ActivityCandidateSemanticEquivalenceAssessment(
        candidate_group=candidate_group,
        status=status,
    )


def _execution(
    status: ExecutionBoundaryEquivalenceStatus,
    *,
    candidate_group: tuple[str, ...] = CANDIDATE_GROUP,
) -> ActivityCandidateExecutionBoundaryEquivalenceAssessment:
    return ActivityCandidateExecutionBoundaryEquivalenceAssessment(
        candidate_group=candidate_group,
        status=status,
    )


def _evaluate(
    *,
    static_eligible: bool = True,
    semantic_status: SemanticEquivalenceStatus = SemanticEquivalenceStatus.CONFIRMED,
    execution_status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.CONFIRMED
    ),
    semantic_group: tuple[str, ...] = CANDIDATE_GROUP,
    execution_group: tuple[str, ...] = CANDIDATE_GROUP,
):
    return MoralActivityCandidateApplicationConditionEvaluator().evaluate(
        static_eligible=static_eligible,
        candidate_group=CANDIDATE_GROUP,
        preferred_activity_type="conversation_with_user",
        semantic_equivalence=_semantic(
            semantic_status,
            candidate_group=semantic_group,
        ),
        execution_boundary_equivalence=_execution(
            execution_status,
            candidate_group=execution_group,
        ),
    )


def test_application_condition_is_ready_only_when_all_conditions_confirmed() -> None:
    result = _evaluate()

    assert result.status is MoralActivityCandidateApplicationConditionStatus.READY
    assert result.ready_for_limited_activation is True
    assert result.static_eligible is True
    assert result.semantic_equivalence_status is SemanticEquivalenceStatus.CONFIRMED
    assert result.execution_boundary_equivalence_status is (
        ExecutionBoundaryEquivalenceStatus.CONFIRMED
    )
    assert result.reasons == (
        "application_condition_ready_but_activation_disabled",
    )


def test_application_condition_is_ineligible_when_static_condition_fails() -> None:
    result = _evaluate(static_eligible=False)

    assert result.status is (
        MoralActivityCandidateApplicationConditionStatus.INELIGIBLE
    )
    assert result.ready_for_limited_activation is False
    assert "moral_static_eligibility_not_satisfied" in result.reasons


def test_application_condition_rejects_explicit_equivalence_rejection() -> None:
    result = _evaluate(
        semantic_status=SemanticEquivalenceStatus.REJECTED,
    )

    assert result.status is MoralActivityCandidateApplicationConditionStatus.REJECTED
    assert result.ready_for_limited_activation is False
    assert result.reasons == ("application_equivalence_rejected",)


def test_application_condition_remains_unconfirmed_for_unknown_boundary() -> None:
    result = _evaluate(
        execution_status=ExecutionBoundaryEquivalenceStatus.UNCONFIRMED,
    )

    assert result.status is (
        MoralActivityCandidateApplicationConditionStatus.UNCONFIRMED
    )
    assert result.ready_for_limited_activation is False
    assert result.reasons == ("application_equivalence_unconfirmed",)


def test_application_condition_rejects_stale_semantic_candidate_group() -> None:
    result = _evaluate(
        semantic_group=("conversation_with_user", "plugin_activity"),
    )

    assert result.status is (
        MoralActivityCandidateApplicationConditionStatus.UNCONFIRMED
    )
    assert result.ready_for_limited_activation is False
    assert result.reasons == (
        "semantic_equivalence_candidate_group_mismatch",
    )


def test_application_condition_rejects_stale_execution_candidate_group() -> None:
    result = _evaluate(
        execution_group=("conversation_with_user", "plugin_activity"),
    )

    assert result.status is (
        MoralActivityCandidateApplicationConditionStatus.UNCONFIRMED
    )
    assert result.ready_for_limited_activation is False
    assert result.reasons == (
        "execution_boundary_candidate_group_mismatch",
    )
