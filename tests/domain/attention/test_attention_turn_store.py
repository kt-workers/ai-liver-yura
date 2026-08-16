from datetime import datetime, timedelta, timezone

import pytest

from app.domain.attention import (
    AttentionClaimRelation,
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
    source_revision: int | None = None,
    expected_source_revision: int | None = None,
) -> AttentionIngressSignal:
    occurred_at = NOW + timedelta(seconds=seconds)
    return AttentionIngressSignal(
        f"signal-{operation.value}-{source_ref}-{revision}-{seconds}",
        operation,
        source_ref,
        kind,
        revision,
        occurred_at,
        source_revision=source_revision,
        expected_source_revision=expected_source_revision,
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
        store.offer(
            signal(
                "goal",
                AttentionSourceKind.GOAL,
                revision=3,
                source_revision=1,
            )
        )
    resolved = store.resolve(
        signal("appraisal", revision=4, seconds=3, operation=AttentionIngressOperation.RESOLVE)
    )
    assert resolved.sources == () and state.revision < resolved.revision


def test_versioned_stable_source_requires_open_refresh_and_close_cas() -> None:
    store = AttentionTurnStore()
    store.offer(
        signal(
            "goal",
            AttentionSourceKind.GOAL,
            source_revision=1,
        )
    )
    refreshed = store.offer(
        signal(
            "goal",
            AttentionSourceKind.GOAL,
            seconds=2,
            operation=AttentionIngressOperation.REFRESH,
            source_revision=2,
            expected_source_revision=1,
        )
    )
    before = refreshed
    with pytest.raises(ValueError, match="stale"):
        store.offer(
            signal(
                "goal",
                AttentionSourceKind.GOAL,
                seconds=3,
                operation=AttentionIngressOperation.REFRESH,
                source_revision=3,
                expected_source_revision=1,
            )
        )
    assert store.snapshot() == before
    with pytest.raises(ValueError, match="stale"):
        store.resolve(
            signal(
                "goal",
                AttentionSourceKind.GOAL,
                seconds=3,
                operation=AttentionIngressOperation.RESOLVE,
                source_revision=3,
                expected_source_revision=1,
            )
        )
    assert store.snapshot() == before
    closed = store.resolve(
        signal(
            "goal",
            AttentionSourceKind.GOAL,
            seconds=4,
            operation=AttentionIngressOperation.RESOLVE,
            source_revision=3,
            expected_source_revision=2,
        )
    )
    assert closed.sources == ()


@pytest.mark.parametrize(
    "kind", (AttentionSourceKind.GOAL, AttentionSourceKind.COMMITMENT, AttentionSourceKind.ACTIVITY)
)
def test_versioned_close_before_open_is_rejected_without_mutation(
    kind: AttentionSourceKind,
) -> None:
    store = AttentionTurnStore()
    before = store.snapshot()
    close = signal(
        "stable-source",
        kind,
        revision=1,
        operation=AttentionIngressOperation.RESOLVE,
        source_revision=2,
        expected_source_revision=1,
    )
    with pytest.raises(ValueError, match="resolve対象"):
        store.resolve(close)
    assert store.snapshot() == before
    store.offer(
        signal("stable-source", kind, revision=1, source_revision=1)
    )
    closed = store.resolve(close)
    assert closed.sources == ()


def test_duplicate_versioned_lifecycle_fact_is_no_commit() -> None:
    store = AttentionTurnStore()
    store.offer(signal("goal", AttentionSourceKind.GOAL, source_revision=1))
    refresh = signal(
        "goal",
        AttentionSourceKind.GOAL,
        seconds=2,
        operation=AttentionIngressOperation.REFRESH,
        source_revision=2,
        expected_source_revision=1,
    )
    store.offer(refresh)
    before = store.snapshot()
    with pytest.raises(ValueError, match="stale"):
        store.offer(refresh)
    assert store.snapshot() == before


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


def test_direct_user_foreground_blocks_lower_priority_interrupt_claims() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    store.offer(signal("normal", AttentionSourceKind.APPRAISAL, seconds=2))
    store.offer(
        signal(
            "foreground",
            AttentionSourceKind.GOAL,
            seconds=3,
            priority=AttentionPriority.FOREGROUND,
            source_revision=1,
        )
    )
    store.offer(signal("background", AttentionSourceKind.REFLECTION, seconds=4))
    store.apply(
        1,
        (
            transition(
                AttentionTransitionOperation.ACQUIRE_FOREGROUND,
                4,
                1,
                target_ref="user",
                source_intent_ref="intent-user",
            ),
            transition(AttentionTransitionOperation.ASSIGN_TURN, 4, 1, value="user"),
            transition(AttentionTransitionOperation.SET_RESPONSE_OBLIGATION, 4, 1, value="user"),
        ),
    )
    claimed = [store.claim_next(0, NOW + timedelta(seconds=5 + item)) for item in range(5)]
    assert {item.source_ref for item in claimed if item is not None} == {"user"}
    assert store.interruption_decision("normal", NOW + timedelta(seconds=10)).allowed is False
    assert store.interruption_decision("foreground", NOW + timedelta(seconds=10)).allowed is False
    assert store.interruption_decision("background", NOW + timedelta(seconds=10)).allowed is False


@pytest.mark.parametrize(
    ("kind", "priority", "source_revision"),
    (
        (AttentionSourceKind.APPRAISAL, AttentionPriority.NORMAL, None),
        (AttentionSourceKind.GOAL, AttentionPriority.FOREGROUND, 1),
    ),
)
def test_claim_relation_separates_continuation_from_challenger_interrupt(
    kind: AttentionSourceKind,
    priority: AttentionPriority,
    source_revision: int | None,
) -> None:
    store = AttentionTurnStore()
    store.offer(
        signal(
            "focus",
            kind,
            seconds=1,
            priority=priority,
            source_revision=source_revision,
        )
    )
    store.apply(
        1,
        (
            transition(
                AttentionTransitionOperation.ACQUIRE_FOREGROUND,
                1,
                1,
                target_ref="focus",
                source_intent_ref="intent-focus",
            ),
        ),
    )
    claimed = store.claim_next(0, NOW + timedelta(seconds=2))
    assert claimed is not None
    assert claimed.source_ref == "focus"
    assert claimed.claim_relation is AttentionClaimRelation.FOREGROUND_CONTINUATION
    assert claimed.interruption_allowed is False


def test_direct_user_obligation_without_foreground_only_claims_direct_users() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user-a", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    store.offer(
        signal("user-b", AttentionSourceKind.USER_INTERACTION, seconds=2, trusted_direct_user=True)
    )
    store.offer(signal("normal", seconds=3))
    store.offer(
        signal(
            "foreground",
            AttentionSourceKind.GOAL,
            seconds=4,
            priority=AttentionPriority.FOREGROUND,
            source_revision=1,
        )
    )
    store.apply(
        1,
        (
            transition(AttentionTransitionOperation.ASSIGN_TURN, 4, 1, value="user-a"),
            transition(AttentionTransitionOperation.SET_RESPONSE_OBLIGATION, 4, 1, value="user-a"),
        ),
    )
    first = store.claim_next(0, NOW + timedelta(seconds=5))
    second = store.claim_next(0, NOW + timedelta(seconds=6))
    third = store.claim_next(0, NOW + timedelta(seconds=7))
    claimed = [item for item in (first, second, third) if item is not None]
    assert {item.source_ref for item in claimed} <= {"user-a", "user-b"}
    assert claimed[0].claim_relation is AttentionClaimRelation.OBLIGATION_CONTINUATION
    assert any(item.source_ref == "user-b" for item in claimed)


def test_direct_user_obligation_blocks_lower_foreground_continuation() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    store.offer(
        signal(
            "game",
            AttentionSourceKind.GOAL,
            seconds=2,
            priority=AttentionPriority.FOREGROUND,
            source_revision=1,
        )
    )
    store.apply(
        1,
        (
            transition(
                AttentionTransitionOperation.ACQUIRE_FOREGROUND,
                2,
                1,
                target_ref="game",
                source_intent_ref="intent-game",
            ),
            transition(AttentionTransitionOperation.ASSIGN_TURN, 2, 1, value="user"),
            transition(AttentionTransitionOperation.SET_RESPONSE_OBLIGATION, 2, 1, value="user"),
        ),
    )
    claimed = store.claim_next(0, NOW + timedelta(seconds=3))
    assert claimed is not None
    assert claimed.source_ref == "user"
    assert claimed.claim_relation is AttentionClaimRelation.OBLIGATION_CONTINUATION


def test_active_non_direct_turn_is_included_in_challenger_threshold() -> None:
    store = AttentionTurnStore()
    store.offer(
        signal(
            "turn",
            AttentionSourceKind.GOAL,
            priority=AttentionPriority.FOREGROUND,
            source_revision=1,
        )
    )
    store.offer(signal("normal", seconds=2))
    store.apply(
        1,
        (transition(AttentionTransitionOperation.ASSIGN_TURN, 2, 1, value="turn"),),
    )
    assert store.interruption_decision("normal", NOW + timedelta(seconds=3)).allowed is False
    claimed = store.claim_next(0, NOW + timedelta(seconds=3))
    assert claimed is not None and claimed.source_ref == "turn"


def test_expired_direct_user_no_longer_protects_claims() -> None:
    store = AttentionTurnStore()
    store.offer(
        signal(
            "user",
            AttentionSourceKind.USER_INTERACTION,
            trusted_direct_user=True,
            expires_in=1,
        )
    )
    store.offer(signal("normal", seconds=2))
    store.apply(
        1,
        (transition(AttentionTransitionOperation.ASSIGN_TURN, 2, 1, value="user"),),
    )
    claimed = store.claim_next(0, NOW + timedelta(seconds=3))
    assert claimed is not None
    assert claimed.source_ref == "normal"
    assert claimed.claim_relation is AttentionClaimRelation.IDLE_START


def test_obligation_release_restores_normal_fairness() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    store.offer(signal("normal", seconds=2))
    store.apply(
        1,
        (
            transition(AttentionTransitionOperation.ASSIGN_TURN, 2, 1, value="user"),
            transition(AttentionTransitionOperation.SET_RESPONSE_OBLIGATION, 2, 1, value="user"),
        ),
    )
    store.apply(
        1,
        (
            transition(AttentionTransitionOperation.RELEASE_TURN, 3, 1),
            transition(AttentionTransitionOperation.CLEAR_RESPONSE_OBLIGATION, 3, 1),
        ),
    )
    first = store.claim_next(0, NOW + timedelta(seconds=4))
    second = store.claim_next(0, NOW + timedelta(seconds=5))
    third = store.claim_next(0, NOW + timedelta(seconds=6))
    assert first is not None and second is not None and third is not None
    assert (first.source_ref, second.source_ref, third.source_ref) == ("user", "user", "normal")


def test_transition_rejects_authoritative_context_advanced_after_creation() -> None:
    store = AttentionTurnStore()
    store.offer(signal("user", AttentionSourceKind.USER_INTERACTION, trusted_direct_user=True))
    old = transition(
        AttentionTransitionOperation.ACQUIRE_FOREGROUND,
        1,
        1,
        target_ref="user",
        source_intent_ref="intent-user",
    )
    before = store.snapshot()
    with pytest.raises(ValueError, match="stale"):
        store.apply(2, (old,))
    assert store.snapshot() == before
    committed = store.apply(1, (old,))
    assert committed.foreground_focus_ref == "user"


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
