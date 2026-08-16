from datetime import datetime, timedelta, timezone

import pytest

from app.domain.attention import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionPriority,
    AttentionSourceKind,
    AttentionTransition,
    AttentionTransitionOperation,
    AttentionTurnStore,
)

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def signal(
    source_ref: str,
    kind: AttentionSourceKind = AttentionSourceKind.APPRAISAL,
    revision: int = 1,
    seconds: int = 1,
    *,
    operation: AttentionIngressOperation = AttentionIngressOperation.OFFER,
    priority: AttentionPriority | None = None,
    trusted_direct_user: bool = False,
    expires_in: int | None = None,
) -> AttentionIngressSignal:
    occurred_at = NOW + timedelta(seconds=seconds)
    return AttentionIngressSignal(
        f"signal-{operation.value}-{source_ref}-{revision}-{seconds}",
        operation,
        source_ref,
        kind,
        revision,
        occurred_at,
        requested_priority=priority,
        expires_at=None if expires_in is None else occurred_at + timedelta(seconds=expires_in),
        trusted_direct_user=trusted_direct_user,
    )


def transition(
    operation: AttentionTransitionOperation,
    attention_revision: int,
    source_revision: int,
    *,
    target_ref: str | None = None,
    value: str | None = None,
    source_intent_ref: str | None = None,
) -> AttentionTransition:
    transition_id = (
        f"transition-{operation.value}-{attention_revision}-{source_revision}-"
        f"{target_ref or value or 'none'}"
    )
    return AttentionTransition(
        transition_id,
        operation,
        attention_revision,
        source_revision,
        NOW + timedelta(seconds=20 + attention_revision),
        target_ref,
        value,
        source_intent_ref,
    )


def test_policy_is_immutable_and_covers_all_source_kinds() -> None:
    policy = AttentionTurnStore().policy
    assert policy.attention_budget == 8
    assert policy.max_same_source_burst == 2
    assert {kind for kind, _ in policy.source_kind_budgets} == set(AttentionSourceKind)


def test_offer_refresh_resolve_and_monotonic_source_context_revision() -> None:
    store = AttentionTurnStore()
    state = store.offer(signal("appraisal", revision=3))
    refreshed = store.offer(
        signal("appraisal", revision=4, seconds=2, operation=AttentionIngressOperation.REFRESH)
    )
    assert refreshed.sources[0].coalesced_count == 2
    with pytest.raises(ValueError, match="巻き戻せません"):
        store.offer(signal("goal", AttentionSourceKind.GOAL, revision=3))
    resolved = store.resolve(
        signal("appraisal", revision=4, seconds=3, operation=AttentionIngressOperation.RESOLVE)
    )
    assert resolved.sources == () and state.revision < resolved.revision


def test_policy_rejects_direct_user_spoofing_and_out_of_range_priority() -> None:
    store = AttentionTurnStore()
    with pytest.raises(ValueError, match="priority"):
        store.offer(
            signal("stream", AttentionSourceKind.STREAMING, priority=AttentionPriority.DIRECT_USER)
        )
    with pytest.raises(ValueError, match="許可範囲"):
        store.offer(
            signal("reflection", AttentionSourceKind.REFLECTION, priority=AttentionPriority.NORMAL)
        )
    state = store.offer(
        signal(
            "user",
            AttentionSourceKind.USER_INTERACTION,
            priority=AttentionPriority.DIRECT_USER,
            trusted_direct_user=True,
        )
    )
    assert state.sources[0].effective_priority is AttentionPriority.DIRECT_USER


def test_budget_and_focus_provenance_are_bounded() -> None:
    store = AttentionTurnStore()
    store.offer(signal("appraisal-1"))
    store.offer(signal("appraisal-2", seconds=2))
    assert store.offer(signal("appraisal-3", seconds=3)) is store.snapshot()
    store.offer(
        signal("user", AttentionSourceKind.USER_INTERACTION, seconds=4, trusted_direct_user=True)
    )
    state = store.apply(
        1,
        (
            transition(
                AttentionTransitionOperation.ACQUIRE_FOREGROUND,
                3,
                1,
                target_ref="user",
                source_intent_ref="intent-user",
            ),
        ),
    )
    assert state.foreground_focus_ref == "user" and state.active_focus_intent_ref == "intent-user"


def test_transition_rejects_stale_context_and_unknown_foreground_source() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    with pytest.raises(ValueError, match="stale"):
        store.apply(1, (transition(AttentionTransitionOperation.RELEASE_FOREGROUND, 0, 0),))
    with pytest.raises(ValueError, match="既知"):
        store.apply(
            1,
            (
                transition(
                    AttentionTransitionOperation.ACQUIRE_FOREGROUND,
                    1,
                    1,
                    target_ref="missing",
                    source_intent_ref="intent",
                ),
            ),
        )


def test_peek_is_read_only_but_claim_records_bounded_same_source_fairness() -> None:
    store = AttentionTurnStore()
    store.offer(signal("a", seconds=1))
    store.offer(signal("b", seconds=2))
    before = store.snapshot()
    assert store.peek_eligibility(0, NOW + timedelta(seconds=3))[0].source_ref == "a"
    assert store.snapshot() == before
    first = store.claim_next(0, NOW + timedelta(seconds=3))
    second = store.claim_next(0, NOW + timedelta(seconds=4))
    assert first is not None and first.source_ref == "a"
    assert second is not None and second.source_ref == "a"
    third = store.claim_next(0, NOW + timedelta(seconds=5))
    assert third is not None and third.source_ref == "b" and store.snapshot().selection_epoch == 3


def test_direct_user_turn_protects_against_background_interruption() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    store.offer(signal("reflection", AttentionSourceKind.REFLECTION, seconds=2))
    store.apply(
        1,
        (
            transition(AttentionTransitionOperation.ASSIGN_TURN, 2, 1, value="user"),
            transition(AttentionTransitionOperation.SET_RESPONSE_OBLIGATION, 2, 1, value="user"),
        ),
    )
    assert store.peek_eligibility(0, NOW + timedelta(seconds=3))[0].source_ref == "user"
    assert store.interruption_decision("reflection", NOW + timedelta(seconds=3)).allowed is False


def test_expiry_and_resolve_clear_invalid_references() -> None:
    store = AttentionTurnStore()
    store.offer(
        signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True, expires_in=1)
    )
    store.apply(
        1,
        (
            transition(
                AttentionTransitionOperation.ACQUIRE_FOREGROUND,
                1,
                1,
                target_ref="user",
                source_intent_ref="intent-user",
            ),
            transition(AttentionTransitionOperation.ASSIGN_TURN, 1, 1, value="user"),
            transition(AttentionTransitionOperation.SET_RESPONSE_OBLIGATION, 1, 1, value="user"),
        ),
    )
    expired = store.expire(1, NOW + timedelta(seconds=3))
    assert expired.foreground_focus_ref is None and expired.active_focus_intent_ref is None
    assert expired.current_turn_owner is None and expired.response_obligation is None


def test_transition_batch_is_atomic_and_duplicate_transition_is_rejected() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    first = transition(
        AttentionTransitionOperation.ACQUIRE_FOREGROUND,
        1,
        1,
        target_ref="user",
        source_intent_ref="intent",
    )
    with pytest.raises(ValueError, match="monitorが存在"):
        store.apply(
            1,
            (
                first,
                transition(AttentionTransitionOperation.REMOVE_MONITOR, 1, 1, target_ref="missing"),
            ),
        )
    assert store.snapshot().revision == 1
    store.apply(1, (first,))
    with pytest.raises(ValueError, match="適用済み"):
        store.apply(1, (first,))
