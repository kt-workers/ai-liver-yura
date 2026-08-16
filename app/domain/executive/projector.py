from __future__ import annotations

from app.domain.contracts import (
    AuthorityRef,
    ExecutiveDecision,
    IntentKind,
    IntentRef,
    PreconditionRef,
    RevisionVector,
    SystemCommand,
)

from .contracts import CommittedExecutiveDecision, ExecutiveIntent, ExecutiveIntentKind

_KINDS = {
    ExecutiveIntentKind.SPEECH: IntentKind.SPEECH,
    ExecutiveIntentKind.BODY: IntentKind.BODY,
    ExecutiveIntentKind.ACTIVITY: IntentKind.ACTIVITY,
    ExecutiveIntentKind.ATTENTION: IntentKind.ATTENTION,
}


def authority_ref(decision_id: str) -> AuthorityRef:
    return AuthorityRef("executive", "conscious_goal_action", decision_id)


def to_foundation_decision(value: CommittedExecutiveDecision) -> ExecutiveDecision:
    candidate = value.candidate
    refs = [IntentRef(_KINDS[item.kind], item.intent_id) for item in candidate.intents]
    refs.extend(
        IntentRef(IntentKind.GOAL_TRANSITION, item.intent_id)
        for item in candidate.goal_transition_intents
    )
    refs.extend(
        IntentRef(IntentKind.COMMITMENT_TRANSITION, item.intent_id)
        for item in candidate.commitment_transition_intents
    )
    revisions = RevisionVector(
        candidate.source_context_revision, candidate.goal_revision, candidate.attention_revision
    )
    return ExecutiveDecision(
        value.decision_id,
        candidate.source_event_ids,
        tuple(refs),
        authority_ref(value.decision_id),
        revisions,
        value.committed_at,
    )


def to_system_command(
    decision: CommittedExecutiveDecision,
    intent: ExecutiveIntent,
    *,
    command_id: str,
) -> SystemCommand:
    if intent not in decision.candidate.intents:
        raise ValueError("intent does not belong to decision")
    revisions = RevisionVector(
        decision.candidate.source_context_revision,
        decision.candidate.goal_revision,
        decision.candidate.attention_revision,
    )
    facts = {item.precondition_id: item for item in decision.validated_preconditions}
    preconditions = tuple(
        PreconditionRef(
            requirement.precondition_id,
            facts[requirement.precondition_id].predicate,
            facts[requirement.precondition_id].subject_ref,
            requirement.expected,
        )
        for requirement in intent.preconditions
    )
    return SystemCommand(
        command_id,
        decision.decision_id,
        IntentRef(_KINDS[intent.kind], intent.intent_id),
        authority_ref(decision.decision_id),
        decision.committed_at,
        revisions,
        preconditions=preconditions,
        required_capabilities=intent.required_capabilities,
    )
