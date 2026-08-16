from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from app.domain.activity_execution import ActivityExecutionLifecycleFact
from app.domain.appraisal import AppraisalCandidate
from app.domain.attention import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionSourceKind,
)
from app.domain.contracts import SourceLifecycleOperation
from app.domain.contracts.common import require_revision
from app.domain.goals import CommitmentLifecycleProjectionFact, GoalLifecycleProjectionFact
from app.domain.input_gateway import InputAdmission, InputAdmissionStatus, InputModality

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class AttentionProjectionEnvelope(Generic[T]):
    """Application境界でowner factへ現在のsource contextを付与する。"""

    owner_fact: T
    source_context_revision: int

    def __post_init__(self) -> None:
        require_revision(self.source_context_revision, "source_context_revision")


class UserInteractionAttentionProjector:
    def project(self, admission: InputAdmission) -> AttentionIngressSignal:
        if (
            not isinstance(admission, InputAdmission)
            or admission.status is not InputAdmissionStatus.ACCEPTED
        ):
            raise ValueError("accepted Input Gateway admissionだけを受理します")
        event = admission.event
        assert event is not None
        if event.modality not in {
            InputModality.TEXT,
            InputModality.SPEECH,
            InputModality.AUDIO,
            InputModality.POINTER,
            InputModality.TOUCH,
        }:
            raise ValueError("user interaction modalityだけを受理します")
        envelope = event.envelope
        return AttentionIngressSignal(
            f"attention-signal-{envelope.event_id}",
            AttentionIngressOperation.OFFER,
            envelope.event_id,
            AttentionSourceKind.USER_INTERACTION,
            envelope.revisions.source_context_revision,
            envelope.occurred_at,
            trusted_direct_user=True,
        )


class AppraisalAttentionProjector:
    def project(self, candidate: AppraisalCandidate) -> AttentionIngressSignal:
        if not isinstance(candidate, AppraisalCandidate):
            raise ValueError("typed AppraisalCandidateだけを受理します")
        return AttentionIngressSignal(
            f"attention-signal-{candidate.candidate_id}",
            AttentionIngressOperation.OFFER,
            candidate.candidate_id,
            AttentionSourceKind.APPRAISAL,
            candidate.source_context_revision,
            candidate.created_at,
            source_revision=candidate.base_state_revision,
        )


class ActivityAttentionProjector:
    def project(
        self, envelope: AttentionProjectionEnvelope[ActivityExecutionLifecycleFact]
    ) -> AttentionIngressSignal:
        if not isinstance(envelope, AttentionProjectionEnvelope) or not isinstance(
            envelope.owner_fact, ActivityExecutionLifecycleFact
        ):
            raise ValueError("typed Activity execution lifecycle factだけを受理します")
        fact = envelope.owner_fact
        return _lifecycle_signal(
            f"attention-signal-{fact.fact_id}",
            fact.operation,
            fact.command_id,
            AttentionSourceKind.ACTIVITY,
            envelope.source_context_revision,
            fact.occurred_at,
            fact.source_revision,
            fact.expected_source_revision,
        )


class GoalAttentionProjector:
    def project(
        self, envelope: AttentionProjectionEnvelope[GoalLifecycleProjectionFact]
    ) -> AttentionIngressSignal:
        if not isinstance(envelope, AttentionProjectionEnvelope) or not isinstance(
            envelope.owner_fact, GoalLifecycleProjectionFact
        ):
            raise ValueError("typed Goal lifecycle factだけを受理します")
        fact = envelope.owner_fact
        return _lifecycle_signal(
            f"attention-signal-{fact.fact_id}",
            fact.operation,
            fact.goal_id,
            AttentionSourceKind.GOAL,
            envelope.source_context_revision,
            fact.occurred_at,
            fact.source_revision,
            fact.expected_source_revision,
        )


class CommitmentAttentionProjector:
    def project(
        self, envelope: AttentionProjectionEnvelope[CommitmentLifecycleProjectionFact]
    ) -> AttentionIngressSignal:
        if not isinstance(envelope, AttentionProjectionEnvelope) or not isinstance(
            envelope.owner_fact, CommitmentLifecycleProjectionFact
        ):
            raise ValueError("typed Commitment lifecycle factだけを受理します")
        fact = envelope.owner_fact
        return _lifecycle_signal(
            f"attention-signal-{fact.fact_id}",
            fact.operation,
            fact.commitment_id,
            AttentionSourceKind.COMMITMENT,
            envelope.source_context_revision,
            fact.occurred_at,
            fact.source_revision,
            fact.expected_source_revision,
        )


def _lifecycle_signal(
    signal_id: str,
    operation: object,
    source_ref: str,
    source_kind: AttentionSourceKind,
    source_context_revision: int,
    occurred_at: datetime,
    source_revision: int,
    expected_source_revision: int | None,
) -> AttentionIngressSignal:
    operations = {
        SourceLifecycleOperation.OPEN: AttentionIngressOperation.OFFER,
        SourceLifecycleOperation.REFRESH: AttentionIngressOperation.REFRESH,
        SourceLifecycleOperation.CLOSE: AttentionIngressOperation.RESOLVE,
    }
    if not isinstance(operation, SourceLifecycleOperation):
        raise ValueError("typed SourceLifecycleOperationが必要です")
    return AttentionIngressSignal(
        signal_id,
        operations[operation],
        source_ref,
        source_kind,
        source_context_revision,
        occurred_at,
        source_revision=source_revision,
        expected_source_revision=expected_source_revision,
    )
