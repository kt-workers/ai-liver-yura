from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.activity_execution import ActivityExecutionRecord
from app.domain.appraisal import AppraisalCandidate
from app.domain.attention import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionSourceKind,
)
from app.domain.contracts import ExecutionStatus
from app.domain.contracts.common import require_aware, require_revision
from app.domain.goals import AutonomyTrigger, AutonomyTriggerKind
from app.domain.input_gateway import InputAdmission, InputAdmissionStatus, InputModality


@dataclass(frozen=True, slots=True)
class GoalCommitmentAttentionFact:
    """Goal/Commitment ownerが発行するbounded change/due fact。"""

    trigger: AutonomyTrigger
    source_context_revision: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, AutonomyTrigger):
            raise ValueError("Goal/Commitmentのtyped triggerが必要です")
        require_revision(self.source_context_revision, "source_context_revision")
        require_aware(self.occurred_at, "occurred_at")


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
            candidate.base_state_revision,
        )


class ActivityAttentionProjector:
    def project(self, record: ActivityExecutionRecord) -> AttentionIngressSignal:
        if not isinstance(record, ActivityExecutionRecord):
            raise ValueError("Activity Intent又はPlanは受理できません")
        result = record.result
        if result.status not in {
            ExecutionStatus.OBSERVABLE,
            ExecutionStatus.APPLIED,
            ExecutionStatus.COMPLETED,
        }:
            raise ValueError("Actual Execution Factだけを受理します")
        return AttentionIngressSignal(
            f"attention-signal-{result.command_id}-{result.status.value}",
            AttentionIngressOperation.OFFER,
            result.command_id,
            AttentionSourceKind.ACTIVITY,
            result.revisions.source_context_revision,
            result.occurred_at,
        )


class GoalAttentionProjector:
    def project(self, fact: GoalCommitmentAttentionFact) -> AttentionIngressSignal:
        if not isinstance(fact, GoalCommitmentAttentionFact) or fact.trigger.kind not in {
            AutonomyTriggerKind.PENDING_GOAL,
            AutonomyTriggerKind.ACTIVE_GOAL,
            AutonomyTriggerKind.SUSPENDED_GOAL,
        }:
            raise ValueError("Goalのtyped change factだけを受理します")
        return _goal_commitment_signal(fact, AttentionSourceKind.GOAL)


class CommitmentAttentionProjector:
    def project(self, fact: GoalCommitmentAttentionFact) -> AttentionIngressSignal:
        if not isinstance(fact, GoalCommitmentAttentionFact) or fact.trigger.kind not in {
            AutonomyTriggerKind.COMMITMENT_REVIEW,
            AutonomyTriggerKind.COMMITMENT_DUE_CHECK,
        }:
            raise ValueError("Commitmentのtyped change/due factだけを受理します")
        return _goal_commitment_signal(fact, AttentionSourceKind.COMMITMENT)


def _goal_commitment_signal(
    fact: GoalCommitmentAttentionFact, kind: AttentionSourceKind
) -> AttentionIngressSignal:
    trigger = fact.trigger
    return AttentionIngressSignal(
        f"attention-signal-{trigger.trigger_id}",
        AttentionIngressOperation.OFFER,
        trigger.source_ref,
        kind,
        fact.source_context_revision,
        fact.occurred_at,
        trigger.goal_revision,
    )
