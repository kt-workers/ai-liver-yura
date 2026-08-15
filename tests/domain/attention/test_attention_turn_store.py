from datetime import datetime, timedelta, timezone

import pytest

from app.domain.attention import (
    AttentionPriority,
    AttentionSource,
    AttentionSourceKind,
    AttentionTransition,
    AttentionTransitionOperation,
    AttentionTurnStore,
    transition_from_executive_intent,
)
from app.domain.executive import (
    AttentionIntentPayload,
    ExecutiveIntent,
    ExecutiveIntentKind,
    SpeechIntentPayload,
)

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def transition(
    operation: AttentionTransitionOperation,
    revision: int,
    *,
    target_ref: str | None = None,
    value: str | None = None,
) -> AttentionTransition:
    return AttentionTransition(
        f"transition-{operation.value}-{revision}-{target_ref or value or 'none'}",
        operation,
        revision,
        NOW + timedelta(seconds=revision),
        target_ref,
        value,
    )


def source(
    source_ref: str,
    priority: AttentionPriority = AttentionPriority.NORMAL,
    kind: AttentionSourceKind = AttentionSourceKind.APPRAISAL,
    seconds: int = 1,
) -> AttentionSource:
    return AttentionSource(source_ref, kind, priority, NOW + timedelta(seconds=seconds))


def test_transition_updates_focus_turn_and_obligation_atomically() -> None:
    store = AttentionTurnStore()
    state = store.apply(
        3,
        (
            transition(AttentionTransitionOperation.ACQUIRE_FOREGROUND, 0, target_ref="user-1"),
            transition(AttentionTransitionOperation.ADD_MONITOR, 0, target_ref="stream-1"),
            transition(AttentionTransitionOperation.ASSIGN_TURN, 0, value="user-1"),
            transition(AttentionTransitionOperation.SET_RESPONSE_OBLIGATION, 0, value="reply-1"),
        ),
    )
    assert state.revision == 1
    assert state.source_context_revision == 3
    assert state.foreground_focus_ref == state.current_turn_owner == "user-1"
    assert state.secondary_monitor_refs == ("stream-1",)
    assert state.response_obligation == "reply-1"


def test_stale_or_duplicate_transition_fails_without_mutation() -> None:
    store = AttentionTurnStore()
    first = transition(AttentionTransitionOperation.ACQUIRE_FOREGROUND, 0, target_ref="user")
    store.apply(1, (first,))
    with pytest.raises(ValueError, match="stale"):
        store.apply(2, (transition(AttentionTransitionOperation.RELEASE_FOREGROUND, 0),))
    with pytest.raises(ValueError, match="適用済み"):
        store.apply(2, (first,))
    assert store.snapshot().revision == 1


def test_invalid_batch_rolls_back_all_changes() -> None:
    store = AttentionTurnStore()
    with pytest.raises(ValueError, match="monitorが存在"):
        store.apply(
            1,
            (
                transition(AttentionTransitionOperation.ACQUIRE_FOREGROUND, 0, target_ref="user"),
                transition(AttentionTransitionOperation.REMOVE_MONITOR, 0, target_ref="missing"),
            ),
        )
    assert store.snapshot().foreground_focus_ref is None
    assert store.snapshot().revision == 0


def test_source_is_coalesced_without_raw_payload_or_mutable_alias() -> None:
    store = AttentionTurnStore()
    store.offer(1, source("comment", seconds=1))
    state = store.offer(2, source("comment", AttentionPriority.FOREGROUND, seconds=2))
    assert state.sources[0].coalesced_count == 2
    assert state.sources[0].priority is AttentionPriority.FOREGROUND
    assert "payload" not in state.sources[0].to_dict()


def test_user_interaction_cannot_be_demoted_and_public_values_serialize() -> None:
    with pytest.raises(ValueError, match="direct user"):
        source("user", AttentionPriority.NORMAL, AttentionSourceKind.USER_INTERACTION)
    item = transition(AttentionTransitionOperation.RELEASE_FOREGROUND, 0)
    assert item.to_dict()["operation"] == "release_foreground"


def test_only_typed_executive_attention_intent_can_create_transition() -> None:
    intent = ExecutiveIntent(
        "attention-1",
        ExecutiveIntentKind.ATTENTION,
        "focus user",
        AttentionIntentPayload("user-1", "acquire_foreground"),
    )
    transition_value = transition_from_executive_intent(intent, 4, NOW)
    assert transition_value.operation is AttentionTransitionOperation.ACQUIRE_FOREGROUND
    assert transition_value.target_ref == "user-1"
    wrong = ExecutiveIntent(
        "speech-1", ExecutiveIntentKind.SPEECH, "speak", SpeechIntentPayload("semantic-1")
    )
    with pytest.raises(ValueError, match="attention intent"):
        transition_from_executive_intent(wrong, 4, NOW)


def test_budget_rejects_equal_priority_then_replaces_lower_priority() -> None:
    store = AttentionTurnStore(attention_budget=1)
    first = store.offer(1, source("background", AttentionPriority.BACKGROUND, seconds=1))
    assert store.offer(2, source("normal", AttentionPriority.BACKGROUND, seconds=2)) is first
    state = store.offer(
        3, source("user", AttentionPriority.DIRECT_USER, AttentionSourceKind.USER_INTERACTION, 3)
    )
    assert tuple(item.source_ref for item in state.sources) == ("user",)


def test_eligibility_prioritizes_user_then_oldest_equal_priority_for_fairness() -> None:
    store = AttentionTurnStore(attention_budget=3)
    store.offer(1, source("later", AttentionPriority.NORMAL, seconds=3))
    store.offer(2, source("earlier", AttentionPriority.NORMAL, seconds=2))
    store.offer(
        3, source("user", AttentionPriority.DIRECT_USER, AttentionSourceKind.USER_INTERACTION, 4)
    )
    entries = store.eligibility(7, NOW + timedelta(seconds=5), limit=3)
    assert [item.source_ref for item in entries] == ["user", "earlier", "later"]
    assert all(item.goal_revision == 7 for item in entries)
    assert all(item.attention_revision == store.snapshot().revision for item in entries)


@pytest.mark.parametrize(
    ("operation", "target_ref", "value"),
    [
        (AttentionTransitionOperation.ACQUIRE_FOREGROUND, None, None),
        (AttentionTransitionOperation.RELEASE_FOREGROUND, "unexpected", None),
        (AttentionTransitionOperation.ASSIGN_TURN, None, None),
        (AttentionTransitionOperation.CLEAR_RESPONSE_OBLIGATION, None, "unexpected"),
    ],
)
def test_transition_rejects_operation_payload_mismatch(
    operation: AttentionTransitionOperation, target_ref: str | None, value: str | None
) -> None:
    with pytest.raises(ValueError, match="payload|指定"):
        transition(operation, 0, target_ref=target_ref, value=value)
