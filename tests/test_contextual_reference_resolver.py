from __future__ import annotations

import pytest

from app.domain.activities import Activity, ActivityType
from app.runtime.contextual_reference_resolver import ContextualReferenceResolver

pytestmark = pytest.mark.unit


def test_repeat_reference_uses_previous_user_turn_from_conversation_history() -> None:
    activity = _repeat_activity(
        history=(
            {"role": "user", "text": "深海魚の発光について説明して"},
            {"role": "assistant", "text": "深海魚の発光には複数の役割があるよ。"},
            {"role": "user", "text": "もう一回説明して"},
        )
    )

    reference = ContextualReferenceResolver().resolve(activity)

    assert reference is not None
    assert reference.relation == "repeat"
    assert reference.source_text == "深海魚の発光について説明して"
    assert reference.resolved_from == "conversation_history"


def test_execution_history_is_preferred_over_newer_unstructured_user_turn() -> None:
    activity = _repeat_activity(
        history=(
            {
                "role": "user",
                "text": "右手を挙げて",
                "turn_id": "turn-action",
                "executed_operation": {
                    "kind": "body_action",
                    "payload": {"body_actions": ["right_hand_raise"]},
                },
                "execution_status": "completed",
                "repeatable": True,
            },
            {"role": "assistant", "text": "できたよ。"},
            {"role": "user", "text": "いい感じ"},
            {"role": "assistant", "text": "ありがとう。"},
            {"role": "user", "text": "もう一回やって"},
        )
    )

    reference = ContextualReferenceResolver().resolve(activity)

    assert reference is not None
    assert reference.source_turn_id == "turn-action"
    assert reference.source_text == "右手を挙げて"
    assert reference.resolved_from == "execution_history"
    assert reference.executed_operation == {
        "kind": "body_action",
        "payload": {"body_actions": ["right_hand_raise"]},
    }


def test_resolved_reference_from_input_meaning_has_priority_over_history() -> None:
    activity = _repeat_activity(
        references=(
            {
                "relation": "repeat",
                "resolved_turn_id": "turn-explicit",
                "resolved_text": "前に説明した海流の話を続けて",
                "confidence": 0.97,
            },
        ),
        history=(
            {"role": "user", "text": "別の話をして"},
            {"role": "user", "text": "もう一回やって"},
        ),
    )

    reference = ContextualReferenceResolver().resolve(activity)

    assert reference is not None
    assert reference.source_turn_id == "turn-explicit"
    assert reference.source_text == "前に説明した海流の話を続けて"
    assert reference.resolved_from == "structured_input_meaning"
    assert reference.confidence == pytest.approx(0.97)


def test_non_repeat_input_does_not_resolve_previous_turn() -> None:
    activity = _repeat_activity(
        text="右手を挙げて",
        primary_intent="control_avatar_body",
        references=(),
        history=({"role": "user", "text": "左を見て"},),
    )

    assert ContextualReferenceResolver().resolve(activity) is None


def _repeat_activity(
    *,
    text: str = "もう一回やって",
    primary_intent: str = "repeat_previous_action",
    references: tuple[dict[str, object], ...] = (),
    history: tuple[dict[str, object], ...],
) -> Activity:
    meaning = {
        "input_speech_act": "command",
        "primary_intent": primary_intent,
        "expected_response": "action",
        "target": None,
        "entities": [],
        "references": [dict(reference) for reference in references],
        "information_provided": [text],
        "confidence": 0.96,
        "source_text": text,
    }
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="文脈参照を解決する",
        context={
            "structured_input_meaning": meaning,
            "event_payload": {
                "text": text,
                "conversation_history": [dict(item) for item in history],
            },
        },
    )
