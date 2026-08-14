from __future__ import annotations

from threading import Lock

from app.domain.contracts.common import RevisionVector, freeze_json

from .contracts import (
    CommittedExecutiveDecision,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
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
        current_revisions: RevisionVector,
        decision_id: str,
        committed_at: object,
    ) -> CommittedExecutiveDecision:
        from datetime import datetime

        if not isinstance(committed_at, datetime):
            raise ValueError("committed_at must be datetime")
        with self._lock:
            if snapshot.trigger_id in self._committed_triggers:
                raise ValueError("executive trigger is already committed")
            self._validate(candidate, snapshot, current_revisions)
            required_precondition_ids = {
                requirement.precondition_id
                for intent in candidate.intents
                for requirement in intent.preconditions
            }
            validated_preconditions = tuple(
                item
                for item in snapshot.preconditions
                if item.precondition_id in required_precondition_ids
            )
            decision = CommittedExecutiveDecision(
                decision_id,
                candidate,
                validated_preconditions,
                committed_at,
            )
            self._committed_triggers.add(snapshot.trigger_id)
            return decision

    @staticmethod
    def _validate(
        candidate: ExecutiveDecisionCandidate,
        snapshot: ExecutiveContextSnapshot,
        current: RevisionVector,
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
        actual = (
            current.source_context_revision,
            current.goal_revision,
            current.attention_revision,
        )
        if candidate.trigger_id != snapshot.trigger_id:
            raise ValueError("candidate trigger does not match snapshot")
        if candidate.source_event_ids != snapshot.source_event_ids:
            raise ValueError("candidate source events do not match snapshot")
        if proposed != expected or actual != expected:
            raise ValueError("executive decision is stale")

        evidence_ids = set(snapshot.source_event_ids)
        evidence_ids.update(item.fact_id for item in snapshot.facts)
        evidence_ids.update(item.capability_id for item in snapshot.capabilities)
        evidence_ids.update(item.precondition_id for item in snapshot.preconditions)
        goal_fact_ids = {item.fact_id for item in snapshot.facts if item.kind.value == "goal"}
        commitment_fact_ids = {
            item.fact_id for item in snapshot.facts if item.kind.value == "commitment"
        }
        references = list(candidate.rationale_refs)
        for intent in candidate.intents:
            references.extend(intent.evidence_refs)
            references.extend(intent.forbidden_claim_refs)
            references.extend(intent.payload.reference_ids())
            unknown_preconditions = {item.precondition_id for item in intent.preconditions} - {
                item.precondition_id for item in snapshot.preconditions
            }
            if unknown_preconditions:
                raise ValueError("intent precondition is outside snapshot")
            for capability_requirement in intent.required_capabilities:
                if not any(
                    item.satisfies(capability_requirement) for item in snapshot.capabilities
                ):
                    raise ValueError("required capability is unavailable")
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

        preconditions = {
            item.precondition_id: freeze_json(item.actual) for item in snapshot.preconditions
        }
        for intent in candidate.intents:
            for precondition_requirement in intent.preconditions:
                if preconditions.get(precondition_requirement.precondition_id) != freeze_json(
                    precondition_requirement.expected
                ):
                    raise ValueError("required precondition does not match")

    def has_committed(self, trigger_id: str) -> bool:
        with self._lock:
            return trigger_id in self._committed_triggers
