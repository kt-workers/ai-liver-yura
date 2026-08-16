from __future__ import annotations

from datetime import datetime

from app.domain.executive import AttentionIntentPayload, ExecutiveIntent, ExecutiveIntentKind

from .contracts import AttentionTransition, AttentionTransitionOperation


def transition_from_executive_intent(
    intent: ExecutiveIntent, expected_attention_revision: int, occurred_at: datetime
) -> AttentionTransition:
    """Executiveのtyped Attention IntentだけをState transitionへ射影する。"""
    if not isinstance(intent, ExecutiveIntent) or intent.kind is not ExecutiveIntentKind.ATTENTION:
        raise ValueError("Executiveのattention intentだけを受理できます")
    payload = intent.payload
    if not isinstance(payload, AttentionIntentPayload):
        raise ValueError("attention intent payloadが不正です")
    mode_to_operation = {
        "acquire_foreground": AttentionTransitionOperation.ACQUIRE_FOREGROUND,
        "release_foreground": AttentionTransitionOperation.RELEASE_FOREGROUND,
        "add_monitor": AttentionTransitionOperation.ADD_MONITOR,
        "remove_monitor": AttentionTransitionOperation.REMOVE_MONITOR,
        "assign_turn": AttentionTransitionOperation.ASSIGN_TURN,
        "release_turn": AttentionTransitionOperation.RELEASE_TURN,
        "set_response_obligation": AttentionTransitionOperation.SET_RESPONSE_OBLIGATION,
        "clear_response_obligation": AttentionTransitionOperation.CLEAR_RESPONSE_OBLIGATION,
    }
    try:
        operation = mode_to_operation[payload.mode]
    except KeyError as error:
        raise ValueError("未対応のattention intent modeです") from error
    if operation in {
        AttentionTransitionOperation.ASSIGN_TURN,
        AttentionTransitionOperation.SET_RESPONSE_OBLIGATION,
    }:
        return AttentionTransition(
            intent.intent_id,
            operation,
            expected_attention_revision,
            occurred_at,
            value=payload.target_ref,
        )
    if operation in {
        AttentionTransitionOperation.RELEASE_FOREGROUND,
        AttentionTransitionOperation.RELEASE_TURN,
        AttentionTransitionOperation.CLEAR_RESPONSE_OBLIGATION,
    }:
        return AttentionTransition(
            intent.intent_id,
            operation,
            expected_attention_revision,
            occurred_at,
        )
    return AttentionTransition(
        intent.intent_id,
        operation,
        expected_attention_revision,
        occurred_at,
        target_ref=payload.target_ref,
    )
