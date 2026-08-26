"""#364 closed Reflection acceptance。"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.memory.contracts import MemoryKind

from .contracts import (
    MemoryCandidateProposal,
    ReflectionAcceptancePolicy,
    ReflectionCandidateResult,
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionPersistenceHint,
    ReflectionSourceEvidence,
    ReflectionSourceKind,
    ReflectionSupportObservation,
    ReflectionSupportRelation,
    candidate_from_accepted_proposal,
)


class ReflectionCandidateAuthority:
    """proposal/supportを閉じたpolicyで#332入力候補へ投影する。"""

    def __init__(self, policy: ReflectionAcceptancePolicy) -> None:
        if not isinstance(policy, ReflectionAcceptancePolicy):
            raise ValueError("policyが不正です")
        self._policy = policy

    def accept(
        self,
        context: ReflectionContextSnapshot,
        proposal: MemoryCandidateProposal,
        support: ReflectionSupportObservation | None,
    ) -> ReflectionCandidateResult:
        source_map = {source.source_ref: source for source in context.primary_sources}
        if support is not None and proposal.proposal_id != support.proposal_id:
            return self._rejected(proposal, ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE)
        if any(source_ref not in source_map for source_ref in proposal.source_refs):
            return self._rejected(proposal, ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE)
        if any(
            source.retracted
            for source in source_map.values()
            if source.source_ref in proposal.source_refs
        ):
            return self._rejected(proposal, ReflectionCandidateStatus.REJECTED_STALE)
        if not self._relation_hints_current(context, proposal):
            return self._rejected(proposal, ReflectionCandidateStatus.REJECTED_STALE)
        if not self._source_claim_is_allowed(proposal, source_map):
            return self._rejected(proposal, ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE)
        if support is None:
            return self._rejected(proposal, ReflectionCandidateStatus.SUPPORT_PROVIDER_UNAVAILABLE)
        support_refs = (
            *support.evidence_refs,
            *support.unsupported_content_refs,
            *support.contradiction_refs,
        )
        if not set(support_refs).issubset(source_map):
            return self._rejected(proposal, ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE)
        status = self._support_status(proposal, support)
        if status is not ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION:
            return self._rejected(proposal, status, support.evidence_refs)
        candidate = candidate_from_accepted_proposal(proposal, context, support)
        return ReflectionCandidateResult(
            proposal.proposal_id,
            status,
            candidate,
            support.evidence_refs,
            proposal.relation_hints,
        )

    def accept_trusted_deterministic_capture(
        self, context: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
    ) -> ReflectionCandidateResult:
        """trusted callerだけがclosed policyを満たしたexact captureへ使う入口。"""
        return self._accept_deterministic(context, proposal)

    def _accept_deterministic(
        self, context: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
    ) -> ReflectionCandidateResult:
        if proposal.proposed_kind is not MemoryKind.WORKING and not any(
            source.source_kind
            in {ReflectionSourceKind.PRESENTATION_FACT, ReflectionSourceKind.EXECUTION_FACT}
            for source in context.primary_sources
            if source.source_ref in proposal.source_refs
        ):
            return self._rejected(proposal, ReflectionCandidateStatus.REJECTED_POLICY)
        support = ReflectionSupportObservation(
            proposal.proposal_id,
            ReflectionSupportRelation.SUPPORTED,
            proposal.source_refs,
            (),
            (),
            proposal.confidence_hint,
        )
        candidate = candidate_from_accepted_proposal(proposal, context, support)
        return ReflectionCandidateResult(
            proposal.proposal_id,
            ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION,
            candidate,
            proposal.source_refs,
            proposal.relation_hints,
        )

    def _support_status(
        self, proposal: MemoryCandidateProposal, support: ReflectionSupportObservation
    ) -> ReflectionCandidateStatus:
        if support.support_relation is ReflectionSupportRelation.UNSUPPORTED:
            return ReflectionCandidateStatus.REJECTED_UNSUPPORTED
        if support.support_relation is ReflectionSupportRelation.AMBIGUOUS:
            return ReflectionCandidateStatus.REJECTED_AMBIGUOUS
        if support.support_relation is ReflectionSupportRelation.CONTRADICTED:
            return ReflectionCandidateStatus.REJECTED_CONTRADICTED
        if support.support_relation is ReflectionSupportRelation.PARTIALLY_SUPPORTED:
            return ReflectionCandidateStatus.REJECTED_POLICY
        durable = proposal.persistence_hint is ReflectionPersistenceHint.DURABLE
        if durable and self._policy.durable_requires_supported:
            return ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
        return ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION

    @staticmethod
    def _source_claim_is_allowed(
        proposal: MemoryCandidateProposal,
        source_map: Mapping[str, ReflectionSourceEvidence],
    ) -> bool:
        sources = tuple(source_map[source_ref] for source_ref in proposal.source_refs)
        actual_speech = proposal.content.predicate == "actual_speech"
        executed_activity = proposal.content.predicate == "executed_activity"
        if actual_speech:
            return any(
                source.source_kind is ReflectionSourceKind.PRESENTATION_FACT
                for source in sources
            )
        if executed_activity:
            return any(
                source.source_kind is ReflectionSourceKind.EXECUTION_FACT
                for source in sources
            )
        return True

    @staticmethod
    def _relation_hints_current(
        context: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
    ) -> bool:
        revisions = {item.memory_id: item.revision for item in context.related_memory_view}
        source_refs = {source.source_ref for source in context.primary_sources}
        return all(
            revisions.get(hint.related_memory_id) == hint.related_memory_revision
            and hint.related_memory_id in proposal.suggested_related_memory_ids
            and set(hint.evidence_refs).issubset(source_refs)
            for hint in proposal.relation_hints
        )

    @staticmethod
    def _rejected(
        proposal: MemoryCandidateProposal,
        status: ReflectionCandidateStatus,
        diagnostics: tuple[str, ...] = (),
    ) -> ReflectionCandidateResult:
        return ReflectionCandidateResult(proposal.proposal_id, status, None, diagnostics)
