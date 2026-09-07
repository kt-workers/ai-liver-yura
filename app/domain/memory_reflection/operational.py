from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from app.domain.contracts.common import require_identifier, require_revision, utc_instant
from app.domain.memory.ranking import estimate_memory_token_units

from .contracts import (
    MemoryCandidateProposal,
    ReflectionContextSnapshot,
    ReflectionSourceEvidence,
    ReflectionSourceKind,
    ReflectionSupportObservation,
)


class ReflectionOperationalFailureCode(str, Enum):
    CONTEXT_TOO_LARGE = "reflection_context_too_large"
    CONTEXT_ORDER_INVALID = "reflection_context_order_invalid"
    PROPOSAL_RESULT_TOO_LARGE = "reflection_proposal_result_too_large"
    SUPPORT_RESULT_TOO_LARGE = "reflection_support_result_too_large"
    POLICY_STALE = "reflection_operational_policy_stale"


class ReflectionOperationalError(ValueError):
    def __init__(self, code: ReflectionOperationalFailureCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ReflectionOperationalPolicy:
    policy_id: str
    policy_revision: int
    max_primary_sources: int
    max_related_memory_items: int
    max_context_estimated_tokens: int
    max_source_excerpt_codepoints: int
    max_proposals_per_reflection: int
    max_relation_hints_per_proposal: int
    max_evidence_refs_per_proposal: int
    max_concurrent_reflections: int

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "reflection operational policy_id")
        require_revision(self.policy_revision, "reflection operational policy_revision")
        self._require_int(self.max_primary_sources, 1, "max_primary_sources")
        self._require_int(self.max_related_memory_items, 0, "max_related_memory_items")
        self._require_int(
            self.max_context_estimated_tokens,
            1,
            "max_context_estimated_tokens",
        )
        self._require_int(
            self.max_source_excerpt_codepoints,
            0,
            "max_source_excerpt_codepoints",
        )
        self._require_int(
            self.max_proposals_per_reflection,
            1,
            "max_proposals_per_reflection",
        )
        self._require_int(
            self.max_relation_hints_per_proposal,
            0,
            "max_relation_hints_per_proposal",
        )
        self._require_int(
            self.max_evidence_refs_per_proposal,
            1,
            "max_evidence_refs_per_proposal",
        )
        self._require_int(
            self.max_concurrent_reflections,
            1,
            "max_concurrent_reflections",
        )

    def same_generation(self, policy_id: str, policy_revision: int) -> bool:
        return self.policy_id == policy_id and self.policy_revision == policy_revision

    @staticmethod
    def _require_int(value: object, minimum: int, field_name: str) -> None:
        if type(value) is not int or value < minimum:
            raise ValueError(f"{field_name} は{minimum}以上の整数でなければなりません")


class ReflectionOperationalPolicyPort(Protocol):
    def current_reflection_operational_policy(self) -> ReflectionOperationalPolicy: ...


def bound_source_excerpt(
    text: str,
    policy: ReflectionOperationalPolicy,
) -> tuple[str, bool]:
    if not isinstance(text, str):
        raise ValueError("source excerpt は文字列でなければなりません")
    limit = policy.max_source_excerpt_codepoints
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def reflection_source_order_key(
    source: ReflectionSourceEvidence,
) -> tuple[datetime, int, str]:
    return (
        utc_instant(source.occurred_at),
        list(ReflectionSourceKind).index(source.source_kind),
        source.source_ref,
    )


def estimate_reflection_context_tokens(context: ReflectionContextSnapshot) -> int:
    payload = context.to_dict()
    payload.pop("estimated_tokens", None)
    return estimate_memory_token_units(payload)


def validate_reflection_context_bounds(
    context: ReflectionContextSnapshot,
    policy: ReflectionOperationalPolicy,
) -> int:
    if not policy.same_generation(
        context.operational_policy_id,
        context.operational_policy_revision,
    ):
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.POLICY_STALE,
            "Reflection contextのoperational policy generationがcurrentではありません",
        )
    if len(context.primary_sources) > policy.max_primary_sources:
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE,
            "primary_sourcesがpolicy上限を超えています",
        )
    if len(context.related_memory_view) > policy.max_related_memory_items:
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE,
            "related_memory_viewがpolicy上限を超えています",
        )
    ordered = tuple(sorted(context.primary_sources, key=reflection_source_order_key))
    if ordered != context.primary_sources:
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.CONTEXT_ORDER_INVALID,
            "primary_sourcesがcanonical orderではありません",
        )
    for source in context.primary_sources:
        excerpt = source.source_excerpt
        if excerpt is None:
            if source.source_excerpt_truncated:
                raise ReflectionOperationalError(
                    ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE,
                    "excerpt無しでtruncated metadataを立てられません",
                )
            continue
        if len(excerpt) > policy.max_source_excerpt_codepoints:
            raise ReflectionOperationalError(
                ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE,
                "source excerptがpolicy上限を超えています",
            )
    estimated_tokens = estimate_reflection_context_tokens(context)
    if estimated_tokens > policy.max_context_estimated_tokens:
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE,
            "Reflection context token estimateがpolicy上限を超えています",
        )
    return estimated_tokens


def validate_reflection_proposals_bounds(
    proposals: tuple[MemoryCandidateProposal, ...],
    policy: ReflectionOperationalPolicy,
) -> None:
    if len(proposals) > policy.max_proposals_per_reflection:
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.PROPOSAL_RESULT_TOO_LARGE,
            "proposal countがpolicy上限を超えています",
        )
    if len({proposal.proposal_id for proposal in proposals}) != len(proposals):
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.PROPOSAL_RESULT_TOO_LARGE,
            "proposal_idが重複しています",
        )
    for proposal in proposals:
        if len(proposal.relation_hints) > policy.max_relation_hints_per_proposal:
            raise ReflectionOperationalError(
                ReflectionOperationalFailureCode.PROPOSAL_RESULT_TOO_LARGE,
                f"{proposal.proposal_id}: relation hint上限超過",
            )
        evidence_refs = set(proposal.rationale_evidence_refs)
        for hint in proposal.relation_hints:
            evidence_refs.update(hint.evidence_refs)
        if len(evidence_refs) > policy.max_evidence_refs_per_proposal:
            raise ReflectionOperationalError(
                ReflectionOperationalFailureCode.PROPOSAL_RESULT_TOO_LARGE,
                f"{proposal.proposal_id}: evidence ref上限超過",
            )


def validate_reflection_support_bounds(
    support: ReflectionSupportObservation,
    policy: ReflectionOperationalPolicy,
) -> None:
    evidence_refs = {
        *support.evidence_refs,
        *support.unsupported_content_refs,
        *support.contradiction_refs,
    }
    if len(evidence_refs) > policy.max_evidence_refs_per_proposal:
        raise ReflectionOperationalError(
            ReflectionOperationalFailureCode.SUPPORT_RESULT_TOO_LARGE,
            f"{support.proposal_id}: support evidence ref上限超過",
        )
