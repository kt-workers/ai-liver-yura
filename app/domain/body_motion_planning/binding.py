from __future__ import annotations

from app.domain.contracts import IntentKind, SystemCommand
from app.domain.executive import (
    BodyIntentPayload,
    CommittedExecutiveDecision,
    ExecutiveIntent,
    ExecutiveIntentKind,
)

from .contracts import BodyMotionIntentView


def bind_body_motion_intent(
    decision: CommittedExecutiveDecision,
    intent: ExecutiveIntent,
    command: SystemCommand,
) -> BodyMotionIntentView:
    if not isinstance(decision, CommittedExecutiveDecision):
        raise ValueError("decision が不正です")
    if not isinstance(intent, ExecutiveIntent) or intent.kind is not ExecutiveIntentKind.BODY:
        raise ValueError("BODY intent が必要です")
    if not isinstance(command, SystemCommand):
        raise ValueError("command が不正です")
    if intent not in decision.candidate.intents:
        raise ValueError("intent はcommitted decisionに属しません")
    if (
        command.decision_id != decision.decision_id
        or command.intent_ref.kind is not IntentKind.BODY
        or command.intent_ref.intent_id != intent.intent_id
        or command.authority.owner != "executive"
        or command.authority.scope != "conscious_goal_action"
        or command.revisions.source_context_revision != decision.candidate.source_context_revision
        or command.revisions.goal_revision != decision.candidate.goal_revision
        or command.revisions.attention_revision != decision.candidate.attention_revision
    ):
        raise ValueError("SystemCommandがExecutive decisionと一致しません")
    payload = intent.payload
    if not isinstance(payload, BodyIntentPayload):
        raise ValueError("BODY payload が不正です")
    return BodyMotionIntentView(
        decision.decision_id,
        intent.intent_id,
        intent.purpose,
        payload.motion_goal_ref,
        payload.target_ref,
        payload.constraint_refs,
        decision.candidate.source_event_ids,
        command.revisions,
        decision.candidate.priority,
        decision.candidate.interruptibility,
        command.preconditions,
        command.required_capabilities,
    )
