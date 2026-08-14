from __future__ import annotations

from datetime import datetime
from math import exp, isfinite, log

from app.domain.contracts.common import require_aware, require_revision, utc_instant

from .contracts import (
    AppraisalCandidate,
    AppraisalPath,
    DecayPolicy,
    InternalStateFacet,
    InternalStateSnapshot,
    LifecycleAppraisalInput,
    StateDeltaProposal,
)


class InternalStateReducer:
    def commit(
        self,
        snapshot: InternalStateSnapshot,
        candidate: AppraisalCandidate,
        *,
        current_source_context_revision: int,
        committed_at: datetime,
    ) -> InternalStateSnapshot:
        require_revision(current_source_context_revision, "current_source_context_revision")
        require_aware(committed_at, "committed_at")
        if candidate.base_state_revision != snapshot.revision:
            raise ValueError("appraisal candidate is stale for current state")
        if candidate.source_context_revision != current_source_context_revision:
            raise ValueError("appraisal candidate is stale for source context")
        if utc_instant(committed_at) < utc_instant(snapshot.updated_at):
            raise ValueError("commit timestamp cannot predate current state")
        if utc_instant(candidate.created_at) < utc_instant(snapshot.updated_at):
            raise ValueError("candidate timestamp cannot predate current state")
        if utc_instant(committed_at) < utc_instant(candidate.created_at):
            raise ValueError("commit timestamp cannot predate candidate")
        if not candidate.proposals:
            raise ValueError("state commit requires at least one delta proposal")
        by_ref = {item.ref: item for item in snapshot.facets}
        for proposal in candidate.proposals:
            previous = by_ref.get(proposal.facet_ref)
            old_value = 0.0 if previous is None else previous.current
            current = old_value + proposal.delta
            if not -1.0 <= current <= 1.0:
                raise ValueError("state delta result is outside allowed range")
            by_ref[proposal.facet_ref] = InternalStateFacet(
                proposal.facet_ref,
                current,
                old_value,
                proposal.delta,
                proposal.confidence,
                proposal.cause_refs,
                committed_at,
            )
        return InternalStateSnapshot(
            snapshot.revision + 1,
            current_source_context_revision,
            tuple(
                sorted(
                    by_ref.values(),
                    key=lambda item: (
                        item.ref.kind.value,
                        item.ref.state_key,
                        item.ref.target_ref or "",
                    ),
                )
            ),
            committed_at,
        )


def decay_candidate(
    snapshot: InternalStateSnapshot,
    policies: tuple[DecayPolicy, ...],
    *,
    candidate_id: str,
    source_event_id: str,
    source_context_revision: int,
    elapsed_seconds: float,
    created_at: datetime,
    path: AppraisalPath = AppraisalPath.DECAY,
) -> AppraisalCandidate:
    if (
        type(elapsed_seconds) not in (int, float)
        or not isfinite(elapsed_seconds)
        or elapsed_seconds < 0
    ):
        raise ValueError("elapsed_seconds must be a non-negative finite number")
    facets = {item.ref: item for item in snapshot.facets}
    proposals: list[StateDeltaProposal] = []
    for policy in tuple(policies):
        current = facets.get(policy.facet_ref)
        if current is None or current.current == policy.neutral or elapsed_seconds == 0:
            continue
        remaining = exp(-log(2) * elapsed_seconds / policy.half_life_seconds)
        next_value = policy.neutral + (current.current - policy.neutral) * remaining
        proposals.append(
            StateDeltaProposal(
                policy.facet_ref,
                next_value - current.current,
                current.confidence,
                (source_event_id,),
            )
        )
    return AppraisalCandidate(
        candidate_id,
        (source_event_id,),
        source_context_revision,
        snapshot.revision,
        path,
        (),
        tuple(proposals),
        0.0,
        0.0,
        (),
        created_at,
    )


def lifecycle_candidate(
    snapshot: InternalStateSnapshot,
    lifecycle: LifecycleAppraisalInput,
    policies: tuple[DecayPolicy, ...],
    *,
    candidate_id: str,
) -> AppraisalCandidate:
    return decay_candidate(
        snapshot,
        policies,
        candidate_id=candidate_id,
        source_event_id=lifecycle.event_id,
        source_context_revision=lifecycle.source_context_revision,
        elapsed_seconds=lifecycle.downtime_seconds,
        created_at=lifecycle.occurred_at,
        path=AppraisalPath.LIFECYCLE,
    )
