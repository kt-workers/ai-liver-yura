from __future__ import annotations

from enum import Enum
from typing import Protocol

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy

from .contracts import (
    BlindUtteranceObservationCandidate,
    PlanRelationObservationCandidate,
    SemanticVerificationContextSnapshot,
    UtteranceEvidenceRef,
)


class SemanticVerificationBoundsFailureCode(str, Enum):
    OBSERVATION_TOO_LARGE = "semantic_observation_too_large"
    POLICY_STALE = "semantic_verification_policy_stale"


class SemanticVerificationBoundsError(ValueError):
    def __init__(self, code: SemanticVerificationBoundsFailureCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


class SemanticVerificationBoundsPolicyPort(Protocol):
    async def current_policy(
        self, snapshot: SemanticVerificationContextSnapshot
    ) -> BrainOperationalBoundsPolicy: ...


def _require_policy(bounds_policy: BrainOperationalBoundsPolicy) -> BrainOperationalBoundsPolicy:
    if not isinstance(bounds_policy, BrainOperationalBoundsPolicy):
        raise ValueError("容量方針はBrainOperationalBoundsPolicyでなければなりません")
    return bounds_policy


def assert_semantic_verification_policy_generation(
    expected: BrainOperationalBoundsPolicy,
    current: BrainOperationalBoundsPolicy,
) -> None:
    expected_policy = _require_policy(expected)
    current_policy = _require_policy(current)
    if (
        expected_policy.policy_id != current_policy.policy_id
        or expected_policy.policy_revision != current_policy.policy_revision
    ):
        raise SemanticVerificationBoundsError(
            SemanticVerificationBoundsFailureCode.POLICY_STALE,
            "Semantic Verification request generationとcurrent policy generationが一致しません",
        )


def _validate_quote(
    ref: UtteranceEvidenceRef,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    maximum = _require_policy(bounds_policy).semantic_verification.max_quote_codepoints
    actual = len(ref.quote)
    if actual > maximum:
        raise SemanticVerificationBoundsError(
            SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE,
            f"evidence quote codepoints={actual} limit={maximum}",
        )


def validate_blind_candidate_bounds(
    candidate: BlindUtteranceObservationCandidate,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(candidate, BlindUtteranceObservationCandidate):
        raise ValueError("candidateはBlindUtteranceObservationCandidateでなければなりません")
    bounds = _require_policy(bounds_policy).semantic_verification
    if len(candidate.units) > bounds.max_blind_units:
        raise SemanticVerificationBoundsError(
            SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE,
            f"blind_units count={len(candidate.units)} limit={bounds.max_blind_units}",
        )
    for unit in candidate.units:
        evidence_count = len(unit.evidence_refs)
        if evidence_count > bounds.max_evidence_refs_per_unit:
            raise SemanticVerificationBoundsError(
                SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE,
                (
                    f"unit={unit.unit_id} evidence_refs={evidence_count} "
                    f"limit={bounds.max_evidence_refs_per_unit}"
                ),
            )
        act_count = len(unit.interaction_acts)
        if act_count > bounds.max_interaction_acts_per_unit:
            raise SemanticVerificationBoundsError(
                SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE,
                (
                    f"unit={unit.unit_id} interaction_acts={act_count} "
                    f"limit={bounds.max_interaction_acts_per_unit}"
                ),
            )
        for ref in unit.evidence_refs:
            _validate_quote(ref, bounds_policy)


def validate_relation_candidate_bounds(
    candidate: PlanRelationObservationCandidate,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(candidate, PlanRelationObservationCandidate):
        raise ValueError("candidateはPlanRelationObservationCandidateでなければなりません")
    bounds = _require_policy(bounds_policy).semantic_verification
    relation_count = len(candidate.proposition_observations)
    if relation_count > bounds.max_proposition_relations:
        raise SemanticVerificationBoundsError(
            SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE,
            (
                f"proposition_relations count={relation_count} "
                f"limit={bounds.max_proposition_relations}"
            ),
        )
    accounting_count = len(candidate.blind_unit_accounting)
    if accounting_count > bounds.max_accounting_entries:
        raise SemanticVerificationBoundsError(
            SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE,
            (
                f"accounting_entries count={accounting_count} "
                f"limit={bounds.max_accounting_entries}"
            ),
        )
    for observation in candidate.proposition_observations:
        support_count = len(observation.supporting_blind_unit_ids)
        if support_count > bounds.max_supporting_units_per_proposition:
            raise SemanticVerificationBoundsError(
                SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE,
                (
                    f"proposition={observation.proposition_id} supporting_units={support_count} "
                    f"limit={bounds.max_supporting_units_per_proposition}"
                ),
            )
        for ref in observation.evidence_refs:
            _validate_quote(ref, bounds_policy)
    for accounting in candidate.blind_unit_accounting:
        for ref in accounting.evidence_refs:
            _validate_quote(ref, bounds_policy)
