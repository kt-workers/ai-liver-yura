from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from app.domain.morals.activity_candidate_execution_boundary_equivalence import (
    ActivityCandidateExecutionBoundaryEquivalenceAssessment,
    ExecutionBoundaryEquivalenceStatus,
)
from app.domain.morals.activity_candidate_semantic_equivalence import (
    ActivityCandidateSemanticEquivalenceAssessment,
    SemanticEquivalenceStatus,
)


class MoralActivityCandidateApplicationConditionStatus(str, Enum):
    """Moral候補選好を限定適用するための前提充足状態。"""

    INELIGIBLE = "ineligible"
    UNCONFIRMED = "unconfirmed"
    REJECTED = "rejected"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class MoralActivityCandidateApplicationCondition:
    """静的適格性と意味・実行境界を統合したShadow診断結果。"""

    candidate_group: tuple[str, ...] = ()
    preferred_activity_type: str | None = None
    status: MoralActivityCandidateApplicationConditionStatus = (
        MoralActivityCandidateApplicationConditionStatus.UNCONFIRMED
    )
    static_eligible: bool = False
    semantic_equivalence_status: SemanticEquivalenceStatus = (
        SemanticEquivalenceStatus.UNCONFIRMED
    )
    execution_boundary_equivalence_status: (
        ExecutionBoundaryEquivalenceStatus
    ) = ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    reasons: tuple[str, ...] = ()

    @property
    def ready_for_limited_activation(self) -> bool:
        return self.status is MoralActivityCandidateApplicationConditionStatus.READY

    def as_context(self) -> dict[str, object]:
        return {
            "candidate_group": list(self.candidate_group),
            "preferred_activity_type": self.preferred_activity_type,
            "status": self.status.value,
            "ready_for_limited_activation": self.ready_for_limited_activation,
            "static_eligible": self.static_eligible,
            "semantic_equivalence_status": self.semantic_equivalence_status.value,
            "execution_boundary_equivalence_status": (
                self.execution_boundary_equivalence_status.value
            ),
            "reasons": list(self.reasons),
        }


class MoralActivityCandidateApplicationConditionEvaluator:
    """Moral補助選好に必要な全前提を一つの型付き条件へ統合する。"""

    def evaluate(
        self,
        *,
        static_eligible: bool,
        candidate_group: Sequence[str],
        preferred_activity_type: str | None,
        semantic_equivalence: ActivityCandidateSemanticEquivalenceAssessment,
        execution_boundary_equivalence: (
            ActivityCandidateExecutionBoundaryEquivalenceAssessment
        ),
    ) -> MoralActivityCandidateApplicationCondition:
        normalized_group = tuple(
            activity_type.strip()
            for activity_type in candidate_group
            if isinstance(activity_type, str) and activity_type.strip()
        )
        normalized_preferred = (
            preferred_activity_type.strip()
            if isinstance(preferred_activity_type, str)
            and preferred_activity_type.strip()
            else None
        )
        reasons: list[str] = []

        if not static_eligible:
            reasons.append("moral_static_eligibility_not_satisfied")
        if len(normalized_group) < 2 or len(set(normalized_group)) != len(
            normalized_group
        ):
            reasons.append("application_candidate_group_invalid")
        if normalized_preferred not in normalized_group:
            reasons.append("preferred_activity_not_in_candidate_group")

        if reasons:
            return self._result(
                candidate_group=normalized_group,
                preferred_activity_type=normalized_preferred,
                status=MoralActivityCandidateApplicationConditionStatus.INELIGIBLE,
                static_eligible=static_eligible,
                semantic_equivalence=semantic_equivalence,
                execution_boundary_equivalence=execution_boundary_equivalence,
                reasons=tuple(reasons),
            )

        if semantic_equivalence.candidate_group != normalized_group:
            reasons.append("semantic_equivalence_candidate_group_mismatch")
        if execution_boundary_equivalence.candidate_group != normalized_group:
            reasons.append("execution_boundary_candidate_group_mismatch")
        if reasons:
            return self._result(
                candidate_group=normalized_group,
                preferred_activity_type=normalized_preferred,
                status=MoralActivityCandidateApplicationConditionStatus.UNCONFIRMED,
                static_eligible=static_eligible,
                semantic_equivalence=semantic_equivalence,
                execution_boundary_equivalence=execution_boundary_equivalence,
                reasons=tuple(reasons),
            )

        if (
            semantic_equivalence.status is SemanticEquivalenceStatus.REJECTED
            or execution_boundary_equivalence.status
            is ExecutionBoundaryEquivalenceStatus.REJECTED
        ):
            return self._result(
                candidate_group=normalized_group,
                preferred_activity_type=normalized_preferred,
                status=MoralActivityCandidateApplicationConditionStatus.REJECTED,
                static_eligible=static_eligible,
                semantic_equivalence=semantic_equivalence,
                execution_boundary_equivalence=execution_boundary_equivalence,
                reasons=("application_equivalence_rejected",),
            )

        if (
            semantic_equivalence.status is not SemanticEquivalenceStatus.CONFIRMED
            or execution_boundary_equivalence.status
            is not ExecutionBoundaryEquivalenceStatus.CONFIRMED
        ):
            return self._result(
                candidate_group=normalized_group,
                preferred_activity_type=normalized_preferred,
                status=MoralActivityCandidateApplicationConditionStatus.UNCONFIRMED,
                static_eligible=static_eligible,
                semantic_equivalence=semantic_equivalence,
                execution_boundary_equivalence=execution_boundary_equivalence,
                reasons=("application_equivalence_unconfirmed",),
            )

        return self._result(
            candidate_group=normalized_group,
            preferred_activity_type=normalized_preferred,
            status=MoralActivityCandidateApplicationConditionStatus.READY,
            static_eligible=static_eligible,
            semantic_equivalence=semantic_equivalence,
            execution_boundary_equivalence=execution_boundary_equivalence,
            reasons=("application_condition_ready_but_activation_disabled",),
        )

    @staticmethod
    def _result(
        *,
        candidate_group: tuple[str, ...],
        preferred_activity_type: str | None,
        status: MoralActivityCandidateApplicationConditionStatus,
        static_eligible: bool,
        semantic_equivalence: ActivityCandidateSemanticEquivalenceAssessment,
        execution_boundary_equivalence: (
            ActivityCandidateExecutionBoundaryEquivalenceAssessment
        ),
        reasons: tuple[str, ...],
    ) -> MoralActivityCandidateApplicationCondition:
        return MoralActivityCandidateApplicationCondition(
            candidate_group=candidate_group,
            preferred_activity_type=preferred_activity_type,
            status=status,
            static_eligible=static_eligible,
            semantic_equivalence_status=semantic_equivalence.status,
            execution_boundary_equivalence_status=(
                execution_boundary_equivalence.status
            ),
            reasons=reasons,
        )
