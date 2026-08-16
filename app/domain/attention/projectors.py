from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionPriority,
    AttentionSourceKind,
)


@dataclass(frozen=True, slots=True)
class AttentionProjectableFact:
    fact_id: str
    source_context_revision: int
    occurred_at: datetime
    source_revision: int | None = None


class _AttentionProjector:
    _kind: AttentionSourceKind
    _priority: AttentionPriority | None = None
    _trusted_direct_user = False

    def project(
        self,
        fact: AttentionProjectableFact,
        *,
        operation: AttentionIngressOperation = AttentionIngressOperation.OFFER,
        expires_at: datetime | None = None,
    ) -> AttentionIngressSignal:
        if not isinstance(fact, AttentionProjectableFact):
            raise ValueError("projectorはtyped attention factだけを受理します")
        return AttentionIngressSignal(
            f"attention-signal-{fact.fact_id}-{operation.value}",
            operation,
            fact.fact_id,
            self._kind,
            fact.source_context_revision,
            fact.occurred_at,
            fact.source_revision,
            self._priority,
            expires_at,
            self._trusted_direct_user,
        )


class UserInteractionAttentionProjector(_AttentionProjector):
    _kind = AttentionSourceKind.USER_INTERACTION
    _priority = AttentionPriority.DIRECT_USER
    _trusted_direct_user = True


class AppraisalAttentionProjector(_AttentionProjector):
    _kind = AttentionSourceKind.APPRAISAL


class GoalAttentionProjector(_AttentionProjector):
    _kind = AttentionSourceKind.GOAL


class CommitmentAttentionProjector(_AttentionProjector):
    _kind = AttentionSourceKind.COMMITMENT


class ActivityAttentionProjector(_AttentionProjector):
    _kind = AttentionSourceKind.ACTIVITY


class StreamingAttentionProjector(_AttentionProjector):
    _kind = AttentionSourceKind.STREAMING


class GameAttentionProjector(_AttentionProjector):
    _kind = AttentionSourceKind.GAME
