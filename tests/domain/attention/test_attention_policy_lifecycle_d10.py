from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.attention import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionPriority,
    AttentionPriorityRule,
    AttentionSchedulingPolicy,
    AttentionSourceKind,
    AttentionTransition,
    AttentionTransitionOperation,
    AttentionTurnStore,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def policy(revision: int = 1) -> AttentionSchedulingPolicy:
    return replace(AttentionSchedulingPolicy.production(), policy_revision=revision)


def signal(
    source_ref: str,
    *,
    kind: AttentionSourceKind = AttentionSourceKind.APPRAISAL,
    priority: AttentionPriority | None = None,
    source_revision: int | None = None,
    seconds: int = 1,
) -> AttentionIngressSignal:
    return AttentionIngressSignal(
        f"signal:{source_ref}:{seconds}",
        AttentionIngressOperation.OFFER,
        source_ref,
        kind,
        1,
        NOW + timedelta(seconds=seconds),
        source_revision=source_revision,
        requested_priority=priority,
        trusted_direct_user=kind is AttentionSourceKind.USER_INTERACTION,
    )


def with_kind_budget(
    current: AttentionSchedulingPolicy,
    kind: AttentionSourceKind,
    maximum: int,
) -> AttentionSchedulingPolicy:
    return replace(
        current,
        source_kind_budgets=tuple(
            (item_kind, maximum if item_kind is kind else limit)
            for item_kind, limit in current.source_kind_budgets
        ),
    )


def with_priority_rule(
    current: AttentionSchedulingPolicy,
    replacement_rule: AttentionPriorityRule,
) -> AttentionSchedulingPolicy:
    return replace(
        current,
        source_priority_rules=tuple(
            replacement_rule if rule.kind is replacement_rule.kind else rule
            for rule in current.source_priority_rules
        ),
    )


def test_production_store_has_no_hidden_policy_default() -> None:
    constructor = cast(Callable[[], AttentionTurnStore], AttentionTurnStore)
    with pytest.raises(TypeError):
        constructor()


def test_same_generation_same_content_is_idempotent() -> None:
    current = policy()
    store = AttentionTurnStore(current)
    before = store.snapshot()

    result = store.update_policy(current, NOW)

    assert result is before
    assert store.snapshot() is before
    assert store.policy is current


def test_same_generation_different_content_is_rejected_without_mutation() -> None:
    current = policy()
    store = AttentionTurnStore(current)
    before = store.snapshot()
    changed = replace(current, attention_budget=current.attention_budget - 1)

    with pytest.raises(ValueError, match="同一policy generation"):
        store.update_policy(changed, NOW)

    assert store.snapshot() is before
    assert store.policy is current


def test_new_revision_preserves_attention_facts_and_resets_fairness_only() -> None:
    current = policy()
    store = AttentionTurnStore(current)
    store.offer(signal("user", kind=AttentionSourceKind.USER_INTERACTION))
    store.offer(signal("other", seconds=2))
    state = store.snapshot()
    store.apply(
        1,
        (
            AttentionTransition(
                "transition:focus",
                AttentionTransitionOperation.ACQUIRE_FOREGROUND,
                state.revision,
                state.source_context_revision,
                NOW + timedelta(seconds=3),
                target_ref="user",
                source_intent_ref="intent:focus",
            ),
            AttentionTransition(
                "transition:turn",
                AttentionTransitionOperation.ASSIGN_TURN,
                state.revision,
                state.source_context_revision,
                NOW + timedelta(seconds=3),
                value="user",
            ),
            AttentionTransition(
                "transition:obligation",
                AttentionTransitionOperation.SET_RESPONSE_OBLIGATION,
                state.revision,
                state.source_context_revision,
                NOW + timedelta(seconds=3),
                value="user",
            ),
        ),
    )
    first = store.claim_next(0, NOW + timedelta(seconds=4))
    second = store.claim_next(0, NOW + timedelta(seconds=5))
    assert first is not None and second is not None
    before = store.snapshot()
    assert before.selection_epoch == 2
    assert before.last_selected_source_ref is not None
    assert before.cooldowns

    updated = store.update_policy(policy(2), NOW + timedelta(seconds=6))

    assert updated.policy_revision == 2
    assert updated.revision == before.revision + 1
    assert updated.source_context_revision == before.source_context_revision
    assert updated.selection_epoch == before.selection_epoch
    assert updated.sources == before.sources
    assert updated.foreground_focus_ref == before.foreground_focus_ref
    assert updated.active_focus_intent_ref == before.active_focus_intent_ref
    assert updated.current_turn_owner == before.current_turn_owner
    assert updated.response_obligation == before.response_obligation
    assert updated.last_selected_source_ref is None
    assert updated.same_source_burst == 0
    assert updated.last_selected_priority is None
    assert updated.priority_burst == 0
    assert updated.cooldowns == ()


def test_global_budget_shrink_rejects_atomically_without_evicting_sources() -> None:
    current = policy()
    store = AttentionTurnStore(current)
    store.offer(signal("first"))
    store.offer(signal("second", seconds=2))
    before = store.snapshot()
    too_small = replace(current, policy_revision=2, attention_budget=1)

    with pytest.raises(ValueError, match="attention budget"):
        store.update_policy(too_small, NOW + timedelta(seconds=3))

    assert store.snapshot() is before
    assert store.policy is current
    assert {item.source_ref for item in store.snapshot().sources} == {"first", "second"}


def test_source_kind_budget_shrink_rejects_atomically() -> None:
    current = policy()
    store = AttentionTurnStore(current)
    store.offer(signal("first"))
    store.offer(signal("second", seconds=2))
    before = store.snapshot()
    too_small = with_kind_budget(replace(current, policy_revision=2), AttentionSourceKind.APPRAISAL, 1)

    with pytest.raises(ValueError, match="source kind"):
        store.update_policy(too_small, NOW + timedelta(seconds=3))

    assert store.snapshot() is before
    assert store.policy is current


def test_priority_range_change_rejects_current_source_without_clamping() -> None:
    current = policy()
    store = AttentionTurnStore(current)
    store.offer(signal("appraisal"))
    before = store.snapshot()
    stricter = with_priority_rule(
        replace(current, policy_revision=2),
        AttentionPriorityRule(
            AttentionSourceKind.APPRAISAL,
            AttentionPriority.FOREGROUND,
            AttentionPriority.FOREGROUND,
        ),
    )

    with pytest.raises(ValueError, match="priority"):
        store.update_policy(stricter, NOW + timedelta(seconds=2))

    assert store.snapshot() is before
    assert store.snapshot().sources[0].effective_priority is AttentionPriority.NORMAL
    assert store.policy is current


def test_same_policy_revision_cannot_move_backward() -> None:
    store = AttentionTurnStore(policy(2))
    before = store.snapshot()

    with pytest.raises(ValueError, match="revision"):
        store.update_policy(policy(1), NOW)

    assert store.snapshot() is before
    assert store.policy.policy_revision == 2


def test_policy_update_rejects_stale_timestamp_without_mutation() -> None:
    current = policy()
    store = AttentionTurnStore(current)
    store.offer(signal("appraisal", seconds=3))
    before = store.snapshot()

    with pytest.raises(ValueError, match="時刻"):
        store.update_policy(policy(2), NOW + timedelta(seconds=2))

    assert store.snapshot() is before
    assert store.policy is current
