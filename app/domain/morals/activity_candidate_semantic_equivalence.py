from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SemanticEquivalenceDimension(str, Enum):
    """意味的同等性を構成する各観点の確認状態。"""

    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class SemanticEquivalenceStatus(str, Enum):
    """候補グループ全体の意味的同等性評価結果。"""

    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ActivityCandidateSemanticEquivalenceEvidence:
    """意味的同等性評価へ渡す型付き証拠。"""

    candidate_group: tuple[str, ...]
    intent: SemanticEquivalenceDimension = SemanticEquivalenceDimension.UNKNOWN
    operation: SemanticEquivalenceDimension = SemanticEquivalenceDimension.UNKNOWN
    goal: SemanticEquivalenceDimension = SemanticEquivalenceDimension.UNKNOWN
    source: str = "unavailable"
    evidence_id: str | None = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_group = tuple(
            activity_type.strip()
            for activity_type in self.candidate_group
            if activity_type.strip()
        )
        if len(normalized_group) < 2:
            raise ValueError("candidate_group must contain at least two activities")
        if len(set(normalized_group)) != len(normalized_group):
            raise ValueError("candidate_group must not contain duplicates")
        normalized_source = self.source.strip()
        if not normalized_source:
            raise ValueError("source must not be empty")
        normalized_evidence_id = (
            self.evidence_id.strip()
            if isinstance(self.evidence_id, str) and self.evidence_id.strip()
            else None
        )
        object.__setattr__(self, "candidate_group", normalized_group)
        object.__setattr__(self, "source", normalized_source)
        object.__setattr__(self, "evidence_id", normalized_evidence_id)
        object.__setattr__(
            self,
            "reasons",
            tuple(reason.strip() for reason in self.reasons if reason.strip()),
        )

    def as_context(self) -> dict[str, object]:
        return {
            "candidate_group": list(self.candidate_group),
            "intent": self.intent.value,
            "operation": self.operation.value,
            "goal": self.goal.value,
            "source": self.source,
            "evidence_id": self.evidence_id,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ActivityCandidateSemanticEquivalenceAssessment:
    """Shadowへ投影する候補グループの意味的同等性評価。"""

    candidate_group: tuple[str, ...] = ()
    status: SemanticEquivalenceStatus = SemanticEquivalenceStatus.UNCONFIRMED
    intent: SemanticEquivalenceDimension = SemanticEquivalenceDimension.UNKNOWN
    operation: SemanticEquivalenceDimension = SemanticEquivalenceDimension.UNKNOWN
    goal: SemanticEquivalenceDimension = SemanticEquivalenceDimension.UNKNOWN
    source: str = "unavailable"
    evidence_id: str | None = None
    reasons: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        return self.status is SemanticEquivalenceStatus.CONFIRMED

    def as_context(self) -> dict[str, object]:
        return {
            "candidate_group": list(self.candidate_group),
            "status": self.status.value,
            "confirmed": self.confirmed,
            "intent": self.intent.value,
            "operation": self.operation.value,
            "goal": self.goal.value,
            "source": self.source,
            "evidence_id": self.evidence_id,
            "reasons": list(self.reasons),
        }


class ActivityCandidateSemanticEquivalenceEvaluator:
    """型付き証拠から意味的同等性を保守的に評価する。"""

    def evaluate(
        self,
        candidate_group: tuple[str, ...],
        evidence: ActivityCandidateSemanticEquivalenceEvidence | None = None,
    ) -> ActivityCandidateSemanticEquivalenceAssessment:
        normalized_group = tuple(
            activity_type.strip()
            for activity_type in candidate_group
            if activity_type.strip()
        )
        if len(normalized_group) < 2:
            return ActivityCandidateSemanticEquivalenceAssessment(
                candidate_group=normalized_group,
                reasons=("semantic_equivalence_candidate_group_insufficient",),
            )
        if evidence is None:
            return ActivityCandidateSemanticEquivalenceAssessment(
                candidate_group=normalized_group,
                reasons=("semantic_equivalence_evidence_unavailable",),
            )
        if evidence.candidate_group != normalized_group:
            return ActivityCandidateSemanticEquivalenceAssessment(
                candidate_group=normalized_group,
                source=evidence.source,
                evidence_id=evidence.evidence_id,
                reasons=("semantic_equivalence_candidate_group_mismatch",),
            )

        dimensions = (evidence.intent, evidence.operation, evidence.goal)
        reasons = list(evidence.reasons)
        if SemanticEquivalenceDimension.REJECTED in dimensions:
            status = SemanticEquivalenceStatus.REJECTED
            self._append_once(reasons, "semantic_equivalence_rejected")
        elif all(
            dimension is SemanticEquivalenceDimension.CONFIRMED
            for dimension in dimensions
        ):
            if evidence.evidence_id is None or evidence.source == "unavailable":
                status = SemanticEquivalenceStatus.UNCONFIRMED
                self._append_once(
                    reasons,
                    "semantic_equivalence_provenance_missing",
                )
            else:
                status = SemanticEquivalenceStatus.CONFIRMED
                self._append_once(reasons, "semantic_equivalence_confirmed")
        else:
            status = SemanticEquivalenceStatus.UNCONFIRMED
            self._append_once(reasons, "semantic_equivalence_unconfirmed")

        return ActivityCandidateSemanticEquivalenceAssessment(
            candidate_group=normalized_group,
            status=status,
            intent=evidence.intent,
            operation=evidence.operation,
            goal=evidence.goal,
            source=evidence.source,
            evidence_id=evidence.evidence_id,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _append_once(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)
