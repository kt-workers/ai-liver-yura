from __future__ import annotations

from threading import Lock

from app.domain.contracts import RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.plan_execution.contracts import (
    _AUTHORIZATION_PROOF,
    PlanExecutionAuthorization,
)

from .contracts import (
    CommittedExecutiveDecision,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    PlanExecutionIntentPayload,
)


class ExecutiveDecisionAuthority:
    """同一triggerの意思決定を高々1件だけ確定する同期commit authority。"""

    def __init__(self) -> None:
        self._committed_triggers: set[str] = set()
        self._lock = Lock()

    def commit(
        self,
        candidate: ExecutiveDecisionCandidate,
        snapshot: ExecutiveContextSnapshot,
        *,
        current: ExecutiveCommitState,
        decision_id: str,
        committed_at: object,
    ) -> CommittedExecutiveDecision:
        from datetime import datetime

        if not isinstance(committed_at, datetime):
            raise ValueError("committed_at must be datetime")
        with self._lock:
            if snapshot.trigger_id in self._committed_triggers:
                raise ValueError("executive trigger is already committed")
            self._validate(candidate, snapshot, current)
            required_precondition_ids = {
                requirement.precondition_id
                for intent in candidate.intents
                for requirement in intent.preconditions
            }
            validated_preconditions = tuple(
                item
                for item in current.preconditions
                if item.precondition_id in required_precondition_ids
            )
            scopes = {item.scope_id: item for item in snapshot.plan_scopes}
            authorizations = tuple(
                PlanExecutionAuthorization(
                    f"{decision_id}:{intent.intent_id}",
                    decision_id,
                    intent.intent_id,
                    scopes[intent.payload.scope_ref],
                    committed_at,
                    _proof=_AUTHORIZATION_PROOF,
                )
                for intent in candidate.intents
                if isinstance(intent.payload, PlanExecutionIntentPayload)
            )
            decision = CommittedExecutiveDecision(
                decision_id,
                candidate,
                validated_preconditions,
                committed_at,
                snapshot.bounds_provenance,
                authorizations,
            )
            self._committed_triggers.add(snapshot.trigger_id)
            return decision

    @staticmethod
    def _validate(
        candidate: ExecutiveDecisionCandidate,
        snapshot: ExecutiveContextSnapshot,
        current: ExecutiveCommitState,
    ) -> None:
        expected = (
            snapshot.source_context_revision,
            snapshot.goal_revision,
            snapshot.attention_revision,
        )
        proposed = (
            candidate.source_context_revision,
            candidate.goal_revision,
            candidate.attention_revision,
        )
        actual = current.freshness.revisions
        expected_revisions = RevisionVector(*expected)
        if candidate.trigger_id != snapshot.trigger_id:
            raise ValueError("candidate trigger does not match snapshot")
        if candidate.source_event_ids != snapshot.source_event_ids:
            raise ValueError("candidate source events do not match snapshot")
        if proposed != expected or actual != expected_revisions:
            raise ValueError("executive decision is stale")
        if current.freshness.internal_state_revision != snapshot.internal_state.revision:
            raise ValueError("executive internal state is stale")
        if current.freshness.appraisal_facts_revision != snapshot.appraisal_facts.revision:
            raise ValueError("executive appraisal facts are stale")
        if current.bounds_provenance != snapshot.bounds_provenance:
            raise ValueError("executive bounds policy is stale")

        requirements = {item.intent_id: item for item in current.requirements}
        if set(requirements) != {item.intent_id for item in candidate.intents}:
            raise ValueError("authoritative intent requirements are incomplete")

        evidence_ids = set(snapshot.source_event_ids)
        evidence_ids.update(item.fact_id for item in snapshot.facts)
        evidence_ids.update(item.capability_id for item in snapshot.capabilities)
        evidence_ids.update(item.precondition_id for item in snapshot.preconditions)
        goal_fact_ids = {item.fact_id for item in snapshot.facts if item.kind.value == "goal"}
        commitment_fact_ids = {
            item.fact_id for item in snapshot.facts if item.kind.value == "commitment"
        }
        original_evidence_ids = set(evidence_ids)
        evidence_ids.update(item.scope_id for item in snapshot.plan_scopes)
        references = list(candidate.rationale_refs)
        for intent in candidate.intents:
            if isinstance(intent.payload, PlanExecutionIntentPayload):
                captured_scopes = {item.scope_id: item for item in snapshot.plan_scopes}
                live_scopes = {item.scope_id: item for item in current.plan_scopes}
                scope = captured_scopes.get(intent.payload.scope_ref)
                if scope is None or live_scopes.get(intent.payload.scope_ref) != scope:
                    raise ValueError("計画承認対象が存在しないか、判断中に変更されています")
                revisions = RevisionVector(
                    snapshot.source_context_revision,
                    snapshot.goal_revision,
                    snapshot.attention_revision,
                )
                if scope.plan.candidate.revisions != revisions:
                    raise ValueError("計画承認対象の依存版が現在の判断と一致しません")
                needed = {
                    requirement
                    for step in scope.plan.candidate.steps
                    for requirement in step.required_capabilities
                }
                if not needed <= set(intent.required_capabilities):
                    raise ValueError("計画全体に必要な能力を承認意図から省略できません")
                conditions = {
                    condition.precondition_id: condition
                    for binding in scope.bindings
                    for condition in binding.preconditions
                }
                requested = {
                    requirement.precondition_id: requirement.expected
                    for requirement in intent.preconditions
                }
                if any(
                    key not in requested or freeze_json(requested[key]) != condition.expected
                    for key, condition in conditions.items()
                ):
                    raise ValueError("計画全体に必要な事前条件を承認意図から省略できません")
                facts = {fact.precondition_id: fact for fact in snapshot.preconditions}
                if any(
                    key not in facts
                    or facts[key].predicate != condition.predicate
                    or facts[key].subject_ref != condition.subject_ref
                    for key, condition in conditions.items()
                ):
                    raise ValueError("計画の事前条件が判断の根拠と一致しません")
                if any(
                    set(binding.argument_fact_refs) - original_evidence_ids
                    for binding in scope.bindings
                ):
                    raise ValueError("操作引数の由来参照が判断の根拠にありません")
            authoritative = requirements[intent.intent_id]
            if not all(item in intent.required_capabilities for item in authoritative.capabilities):
                raise ValueError("authoritative capability requirement is missing")
            if not all(item in intent.preconditions for item in authoritative.preconditions):
                raise ValueError("authoritative precondition requirement is missing")
            references.extend(intent.evidence_refs)
            references.extend(intent.forbidden_claim_refs)
            references.extend(intent.payload.reference_ids())
            unknown_preconditions = {item.precondition_id for item in intent.preconditions} - {
                item.precondition_id for item in snapshot.preconditions
            }
            if unknown_preconditions:
                raise ValueError("intent precondition is outside snapshot")
            for capability_requirement in intent.required_capabilities:
                captured = tuple(
                    item for item in snapshot.capabilities if item.satisfies(capability_requirement)
                )
                if not captured:
                    raise ValueError("required capability was unavailable in snapshot")
                if not any(
                    live.capability_id == previous.capability_id
                    and live.revision == previous.revision
                    and live.satisfies(capability_requirement)
                    for previous in captured
                    for live in current.capabilities
                ):
                    raise ValueError("required capability changed or is unavailable")
        for transition in candidate.goal_transition_intents:
            if transition.expected_goal_revision != snapshot.goal_revision:
                raise ValueError("goal transition revision is stale")
            references.extend(transition.reason_refs)
            if set(transition.payload.goal_fact_reference_ids()) - goal_fact_ids:
                raise ValueError("goal transition payload reference has an invalid fact kind")
            if set(transition.payload.commitment_fact_reference_ids()) - commitment_fact_ids:
                raise ValueError("goal commitment ref has an invalid fact kind")
            references.extend(transition.payload.bounded_reference_ids())
            target = transition.goal_ref or transition.goal_spec_ref
            if target not in goal_fact_ids:
                raise ValueError("goal transition reference is outside bounded context")
        for commitment_transition in candidate.commitment_transition_intents:
            if commitment_transition.expected_goal_revision != snapshot.goal_revision:
                raise ValueError("commitment transition revision is stale")
            references.extend(commitment_transition.reason_refs)
            if (
                set(commitment_transition.payload.commitment_fact_reference_ids())
                - commitment_fact_ids
            ):
                raise ValueError("commitment transition payload reference has an invalid fact kind")
            if set(commitment_transition.payload.goal_fact_reference_ids()) - goal_fact_ids:
                raise ValueError("commitment goal ref has an invalid fact kind")
            references.extend(commitment_transition.payload.bounded_reference_ids())
            target = (
                commitment_transition.commitment_ref or commitment_transition.commitment_spec_ref
            )
            if target not in commitment_fact_ids:
                raise ValueError("commitment transition reference is outside bounded context")
        if set(references) - evidence_ids:
            raise ValueError("candidate reference is outside bounded context")

        snapshot_preconditions = {item.precondition_id: item for item in snapshot.preconditions}
        current_preconditions = {item.precondition_id: item for item in current.preconditions}
        for intent in candidate.intents:
            for precondition_requirement in intent.preconditions:
                precondition_id = precondition_requirement.precondition_id
                captured_precondition = snapshot_preconditions[precondition_id]
                live = current_preconditions.get(precondition_id)
                if (
                    live is None
                    or live.subject_ref != captured_precondition.subject_ref
                    or live.predicate != captured_precondition.predicate
                    or freeze_json(live.actual) != freeze_json(precondition_requirement.expected)
                ):
                    raise ValueError("required precondition does not match")

    def has_committed(self, trigger_id: str) -> bool:
        with self._lock:
            return trigger_id in self._committed_triggers
