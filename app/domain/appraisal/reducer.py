from __future__ import annotations

from datetime import datetime
from math import isfinite
from threading import Lock

from app.domain.contracts.common import require_aware, require_revision, utc_instant

from .contracts import (
    AppraisalCandidate,
    AppraisalPath,
    DecayDiagnostic,
    DecayDiagnosticCode,
    DecayFacetRule,
    DecayPolicy,
    DecayProposalProvenance,
    DecayTargetScope,
    InternalStateFacet,
    InternalStateSnapshot,
    LifecycleAppraisalInput,
    StateDeltaProposal,
)


class InternalStateReducer:
    def __init__(self, initial_snapshot: InternalStateSnapshot) -> None:
        if not isinstance(initial_snapshot, InternalStateSnapshot):
            raise ValueError("initial_snapshot must be InternalStateSnapshot")
        self._current = initial_snapshot
        self._lock = Lock()

    def snapshot(self) -> InternalStateSnapshot:
        with self._lock:
            return self._current

    def commit(
        self,
        candidate: AppraisalCandidate,
        *,
        current_source_context_revision: int,
        committed_at: datetime,
        current_decay_policy: DecayPolicy | None = None,
    ) -> InternalStateSnapshot:
        if not isinstance(candidate, AppraisalCandidate):
            raise ValueError("candidate must be AppraisalCandidate")
        require_revision(current_source_context_revision, "current_source_context_revision")
        require_aware(committed_at, "committed_at")
        with self._lock:
            snapshot = self._current
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
            allowed_causes = {*candidate.source_event_ids, *candidate.evidence_refs}
            if any(
                not set(proposal.cause_refs) <= allowed_causes for proposal in candidate.proposals
            ):
                raise ValueError("state delta cause is outside candidate evidence")
            by_ref = {item.ref: item for item in snapshot.facets}
            if candidate.path in (AppraisalPath.DECAY, AppraisalPath.LIFECYCLE):
                if current_decay_policy is None:
                    raise ValueError("減衰方針を取得できません")
                for proposal in candidate.proposals:
                    provenance = proposal.decay_provenance
                    if provenance is None:
                        raise ValueError("減衰候補にprovenanceがありません")
                    if (
                        provenance.decay_policy_id != current_decay_policy.policy_id
                        or provenance.decay_policy_revision
                        != current_decay_policy.policy_revision
                    ):
                        raise ValueError("減衰方針が古くなっています")
                    if (
                        provenance.base_state_revision != snapshot.revision
                        or provenance.source_context_revision != current_source_context_revision
                    ):
                        raise ValueError("減衰候補が古くなっています")
                    if proposal.facet_ref not in by_ref:
                        raise ValueError("減衰対象facetがcurrent stateにありません")
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
            next_snapshot = InternalStateSnapshot(
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
            self._current = next_snapshot
            return next_snapshot


def decay_candidate(
    snapshot: InternalStateSnapshot,
    policy: DecayPolicy | None,
    *,
    candidate_id: str,
    source_event_id: str,
    source_context_revision: int,
    evaluated_at: datetime,
    path: AppraisalPath = AppraisalPath.DECAY,
) -> AppraisalCandidate:
    require_aware(evaluated_at, "evaluated_at")
    proposals: list[StateDeltaProposal] = []
    diagnostics: list[DecayDiagnostic] = []
    if policy is None:
        diagnostics.append(DecayDiagnostic(DecayDiagnosticCode.POLICY_UNAVAILABLE))
    else:
        for facet in snapshot.facets:
            rule = _select_decay_rule(policy, facet)
            if rule is None:
                diagnostics.append(
                    DecayDiagnostic(DecayDiagnosticCode.POLICY_RULE_MISSING, facet.ref)
                )
                continue
            elapsed_seconds = max(
                0.0, (utc_instant(evaluated_at) - utc_instant(facet.updated_at)).total_seconds()
            )
            if elapsed_seconds < rule.minimum_elapsed_seconds:
                continue
            decay_factor = 2 ** (-elapsed_seconds / rule.half_life_seconds)
            decayed_value = rule.neutral_baseline + (
                facet.current - rule.neutral_baseline
            ) * decay_factor
            delta = decayed_value - facet.current
            if not isfinite(decay_factor) or not isfinite(decayed_value):
                raise ValueError("減衰計算結果が有限ではありません")
            if not -1.0 <= decayed_value <= 1.0:
                raise ValueError("減衰後の値が許容範囲外です")
            if delta == 0.0:
                continue
            proposals.append(
                StateDeltaProposal(
                    facet.ref,
                    delta,
                    facet.confidence,
                    (source_event_id,),
                    DecayProposalProvenance(
                        policy.policy_id,
                        policy.policy_revision,
                        rule.rule_id,
                        snapshot.revision,
                        source_context_revision,
                        elapsed_seconds,
                        evaluated_at,
                    ),
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
        evaluated_at,
        tuple(diagnostics),
    )


def lifecycle_candidate(
    snapshot: InternalStateSnapshot,
    lifecycle: LifecycleAppraisalInput,
    policy: DecayPolicy | None,
    *,
    candidate_id: str,
) -> AppraisalCandidate:
    return decay_candidate(
        snapshot,
        policy,
        candidate_id=candidate_id,
        source_event_id=lifecycle.event_id,
        source_context_revision=lifecycle.source_context_revision,
        evaluated_at=lifecycle.occurred_at,
        path=AppraisalPath.LIFECYCLE,
    )


def _select_decay_rule(
    policy: DecayPolicy, facet: InternalStateFacet
) -> DecayFacetRule | None:
    scope = (
        DecayTargetScope.TARGETED
        if facet.ref.target_ref is not None
        else DecayTargetScope.GLOBAL
    )
    exact = [
        rule
        for rule in policy.rules
        if rule.facet_kind is facet.ref.kind
        and rule.state_key == facet.ref.state_key
        and rule.target_scope is scope
    ]
    if exact:
        return exact[0]
    default = [
        rule
        for rule in policy.rules
        if rule.facet_kind is facet.ref.kind
        and rule.state_key is None
        and rule.target_scope is scope
    ]
    return default[0] if default else None
