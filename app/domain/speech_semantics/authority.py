from __future__ import annotations

from datetime import datetime
from threading import Lock

from app.domain.contracts import ExecutionStatus, RevisionVector
from app.domain.contracts.common import (
    freeze_json,
    require_aware,
    require_identifier,
    utc_instant,
)
from app.domain.executive import SpeechIntentPayload

from .contracts import (
    _PLAN_PROOF,
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticClaimKind,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
    SpeechSemanticPlan,
    SpeechTruthConstraint,
    SpeechTruthRule,
    _validate_self_disclosure_policy,
)


class SpeechSemanticAuthority:
    """What-to-say candidateをbounded factへgroundして確定する。"""

    def __init__(self) -> None:
        self._plans: dict[str, SpeechSemanticPlan] = {}
        self._intent_ids: set[str] = set()
        self._lock = Lock()

    def commit(
        self,
        candidate: SpeechSemanticCandidate,
        snapshot: SpeechSemanticContextSnapshot,
        *,
        current_revisions: RevisionVector,
        plan_id: str,
        committed_at: datetime,
    ) -> SpeechSemanticPlan:
        if not isinstance(candidate, SpeechSemanticCandidate):
            raise ValueError("candidate must be SpeechSemanticCandidate")
        if not isinstance(snapshot, SpeechSemanticContextSnapshot):
            raise ValueError("snapshot must be SpeechSemanticContextSnapshot")
        if not isinstance(current_revisions, RevisionVector):
            raise ValueError("current_revisions must be RevisionVector")
        require_identifier(plan_id, "plan_id")
        require_aware(committed_at, "committed_at")
        self._validate_identity(candidate, snapshot, current_revisions)
        facts = {item.fact_id: item for item in snapshot.facts}
        constraints = {item.constraint_id: item for item in snapshot.truth_constraints}
        self._validate_refs(candidate, snapshot, facts, constraints)
        self._validate_truth(candidate, facts, constraints)
        with self._lock:
            if plan_id in self._plans:
                raise ValueError("plan id is already committed")
            if candidate.intent_id in self._intent_ids:
                raise ValueError("speech intent is already committed")
            plan = SpeechSemanticPlan(plan_id, candidate, committed_at, _proof=_PLAN_PROOF)
            self._plans[plan_id] = plan
            self._intent_ids.add(candidate.intent_id)
            return plan

    def snapshot(self, plan_id: str) -> SpeechSemanticPlan | None:
        with self._lock:
            return self._plans.get(plan_id)

    @staticmethod
    def _validate_identity(
        candidate: SpeechSemanticCandidate,
        snapshot: SpeechSemanticContextSnapshot,
        current_revisions: RevisionVector,
    ) -> None:
        if candidate.decision_id != snapshot.decision.decision_id:
            raise ValueError("candidate decision does not match snapshot")
        if candidate.intent_id != snapshot.intent_id:
            raise ValueError("candidate intent does not match snapshot")
        if candidate.source_event_ids != snapshot.source_event_ids:
            raise ValueError("candidate source events do not match snapshot")
        if candidate.revisions != snapshot.revisions:
            raise ValueError("candidate revisions do not match snapshot")
        if current_revisions != snapshot.revisions:
            raise ValueError("speech semantic candidate is stale")
        if utc_instant(candidate.created_at) < utc_instant(snapshot.captured_at):
            raise ValueError("candidate cannot predate speech semantic snapshot")

    @staticmethod
    def _validate_refs(
        candidate: SpeechSemanticCandidate,
        snapshot: SpeechSemanticContextSnapshot,
        facts: dict[str, SpeechSemanticFact],
        constraints: dict[str, SpeechTruthConstraint],
    ) -> None:
        for proposition in candidate.propositions:
            if any(ref not in facts for ref in proposition.evidence_fact_refs):
                raise ValueError("proposition evidence is outside bounded facts")
        if set(candidate.truth_constraint_refs) != set(constraints):
            raise ValueError("candidate truth constraints must match authoritative constraints")
        allowed = set(snapshot.available_constraint_refs)
        if any(
            ref not in allowed
            for refs in (
                candidate.relationship_constraint_refs,
                candidate.discourse_constraint_refs,
            )
            for ref in refs
        ):
            raise ValueError("candidate constraint is outside bounded context")
        if candidate.question_budget > snapshot.max_question_budget:
            raise ValueError("question budget exceeds authoritative maximum")
        if candidate.new_direction_budget > snapshot.max_new_direction_budget:
            raise ValueError("new direction budget exceeds authoritative maximum")
        _validate_self_disclosure_policy(candidate.self_disclosure, snapshot.self_disclosure_policy)
        intent = snapshot.intent
        payload = intent.payload
        assert isinstance(payload, SpeechIntentPayload)
        required_grounding = {payload.semantic_goal_ref, *intent.evidence_refs}
        if payload.target_ref is not None:
            required_grounding.add(payload.target_ref)
        for required_ref in required_grounding:
            fact = facts[required_ref]
            if not any(
                proposition.disposition is not SpeechPropositionDisposition.FORBIDDEN
                and required_ref in proposition.evidence_fact_refs
                and _semantic_match(proposition, fact)
                for proposition in candidate.propositions
            ):
                raise ValueError("candidate does not realize required speech intent fact")
        used_constraint_refs = (
            set(candidate.truth_constraint_refs)
            | set(candidate.relationship_constraint_refs)
            | set(candidate.discourse_constraint_refs)
        )
        if not set(payload.constraint_refs).issubset(used_constraint_refs):
            raise ValueError("candidate omits Executive speech constraint")
        self_fact_refs = {
            item.fact_id for item in facts.values() if item.kind is SpeechSemanticFactKind.SELF
        }
        has_self_disclosure = any(
            proposition.disposition is not SpeechPropositionDisposition.FORBIDDEN
            and bool(set(proposition.evidence_fact_refs) & self_fact_refs)
            for proposition in candidate.propositions
        )
        if has_self_disclosure and (
            candidate.self_disclosure is SelfDisclosurePolicy.FORBIDDEN
            or snapshot.self_disclosure_policy is SelfDisclosurePolicy.FORBIDDEN
        ):
            raise ValueError("self disclosure proposition is forbidden")
        for forbidden_ref in intent.forbidden_claim_refs:
            fact = facts[forbidden_ref]
            if not any(
                forbidden_ref in proposition.evidence_fact_refs
                and proposition.disposition is SpeechPropositionDisposition.FORBIDDEN
                and _semantic_match(proposition, fact)
                for proposition in candidate.propositions
            ):
                raise ValueError("forbidden Executive claim is not preserved")

    @staticmethod
    def _validate_truth(
        candidate: SpeechSemanticCandidate,
        facts: dict[str, SpeechSemanticFact],
        constraints: dict[str, SpeechTruthConstraint],
    ) -> None:
        constrained_facts = {item.fact_ref for item in constraints.values()}
        for proposition in candidate.propositions:
            execution_refs = {
                ref
                for ref in proposition.evidence_fact_refs
                if facts[ref].kind is SpeechSemanticFactKind.EXECUTION
            }
            if proposition.claim_kind is SemanticClaimKind.EXECUTION_STATUS and not execution_refs:
                raise ValueError("execution claim requires execution fact evidence")
            if execution_refs and not execution_refs.issubset(constrained_facts):
                raise ValueError("execution evidence requires authoritative truth constraint")
        for constraint in constraints.values():
            fact = facts[constraint.fact_ref]
            related = [
                item
                for item in candidate.propositions
                if constraint.fact_ref in item.evidence_fact_refs
                and item.disposition is not SpeechPropositionDisposition.FORBIDDEN
            ]
            if constraint.rule is SpeechTruthRule.REQUIRE_MATCH:
                if not related or any(not _semantic_match(item, fact) for item in related):
                    raise ValueError("proposition does not match authoritative fact")
            elif constraint.rule is SpeechTruthRule.PRESERVE_UNKNOWN:
                if not related or any(
                    item.polarity is not SemanticPolarity.UNKNOWN
                    or item.certainty is not SemanticCertainty.UNKNOWN
                    or not _semantic_match(item, fact)
                    for item in related
                ):
                    raise ValueError("unknown fact must remain unknown")
            elif constraint.rule is SpeechTruthRule.FORBID_COMPLETION_CLAIM:
                if any(
                    item.claim_kind is SemanticClaimKind.EXECUTION_STATUS
                    and item.execution_status is ExecutionStatus.COMPLETED
                    and item.polarity is SemanticPolarity.AFFIRM
                    for item in related
                ):
                    raise ValueError("execution completion claim is forbidden")


def _semantic_match(proposition: SpeechProposition, fact: SpeechSemanticFact) -> bool:
    return (
        proposition.subject_ref == fact.subject_ref
        and proposition.predicate == fact.predicate
        and freeze_json(proposition.value) == freeze_json(fact.value)
        and proposition.claim_kind is fact.claim_kind
        and proposition.execution_status is fact.execution_status
        and proposition.polarity is fact.polarity
        and proposition.certainty is fact.certainty
        and proposition.degree == fact.degree
    )
