from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from app.domain.attention import (
    AttentionFocusState,
    AttentionResponseSettlement,
    AttentionSourceKind,
    AttentionTurnStore,
)
from app.domain.attention import (
    AttentionTransitionOperation as Op,
)
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationRequest,
    AuthorityFinalizationResult,
    FinalizationFailure,
)
from tests.domain.attention.test_attention_turn_store import (
    NOW,
    attention_store,
    signal,
    transition,
)


def prepared_store(
    turn: str | None = "user-a",
    obligation: str | None = "user-a",
    kind: AttentionSourceKind = AttentionSourceKind.USER_INTERACTION,
) -> AttentionTurnStore:
    store = attention_store()
    store.offer(
        signal("user-a", kind, trusted_direct_user=kind is AttentionSourceKind.USER_INTERACTION)
    )
    store.offer(
        signal("user-b", AttentionSourceKind.USER_INTERACTION, seconds=2, trusted_direct_user=True)
    )
    store.offer(signal("other", seconds=3))
    state = store.snapshot()
    changes = []
    if turn is not None:
        changes.append(transition(Op.ASSIGN_TURN, state.revision, 1, value=turn))
    if obligation is not None:
        changes.append(transition(Op.SET_RESPONSE_OBLIGATION, state.revision, 1, value=obligation))
    if changes:
        store.apply(1, tuple(changes))
    return store


def evidence(store: AttentionTurnStore, **changes: Any) -> AttentionResponseSettlement:
    state = store.snapshot()
    return replace(
        AttentionResponseSettlement(
            "observed-execution",
            2,
            "completed",
            "decision",
            ("user-a",),
            state.revision,
            state.source_context_revision,
            NOW + timedelta(minutes=1),
        ),
        **changes,
    )


def finalize(
    store: AttentionTurnStore, settlement: AttentionResponseSettlement
) -> AuthorityFinalizationResult[AttentionFocusState]:
    return AuthorityFinalizationFence().finalize(
        AuthorityFinalizationRequest(
            store.snapshot_publication().tokens,
            store.finalization_participant,
            store.response_settlement_operation,
            settlement,
        )
    )


@pytest.mark.parametrize(
    ("turn", "obligation", "events", "remaining_turn", "remaining_obligation"),
    [
        ("user-a", None, ("user-a",), None, None),
        (None, "user-a", ("user-a",), None, None),
        ("user-a", "user-a", ("user-a",), None, None),
        ("user-b", "user-a", ("user-a",), "user-b", None),
        ("user-a", "user-b", ("user-a",), None, "user-b"),
        ("user-a", "user-b", ("user-b",), "user-a", None),
    ],
)
def test_unique_current_user_target(
    turn: str | None,
    obligation: str | None,
    events: tuple[str, ...],
    remaining_turn: str | None,
    remaining_obligation: str | None,
) -> None:
    store = prepared_store(turn, obligation)
    before = store.snapshot()
    result = finalize(store, evidence(store, source_event_ids=events))
    assert result.failure is None
    after = store.snapshot()
    assert result.value == after
    assert after.revision == before.revision + 1
    assert after.source_context_revision == before.source_context_revision
    assert after.current_turn_owner == remaining_turn
    assert after.response_obligation == remaining_obligation
    assert after.sources == tuple(s for s in before.sources if s.source_ref != events[0])


@pytest.mark.parametrize(
    ("turn", "obligation", "events", "kind"),
    [
        ("user-a", "user-b", ("user-a", "user-b"), AttentionSourceKind.USER_INTERACTION),
        ("user-a", "user-a", ("other",), AttentionSourceKind.USER_INTERACTION),
        ("missing", "missing", ("missing",), AttentionSourceKind.USER_INTERACTION),
        (None, None, ("user-a",), AttentionSourceKind.USER_INTERACTION),
        ("user-a", "user-a", ("user-a",), AttentionSourceKind.APPRAISAL),
    ],
)
def test_invalid_target_rejects_atomically_without_poisoning(
    turn: str | None,
    obligation: str | None,
    events: tuple[str, ...],
    kind: AttentionSourceKind,
) -> None:
    store = prepared_store(turn, obligation, kind)
    before = store.snapshot()
    result = finalize(store, evidence(store, source_event_ids=events))
    assert result.failure is FinalizationFailure.TARGET_REJECTED
    assert store.snapshot() is before
    assert store.snapshot_publication().value is before
    assert finalize(store, evidence(store, source_event_ids=events)).failure is result.failure


@pytest.mark.parametrize(
    "field", ["expected_attention_revision", "expected_source_context_revision"]
)
def test_expected_revision_is_checked_inside_owner(field: str) -> None:
    store = prepared_store()
    before = store.snapshot()
    assert (
        finalize(store, evidence(store, **{field: 0})).failure
        is FinalizationFailure.TARGET_REJECTED
    )
    assert store.snapshot() is before
    assert finalize(store, evidence(store)).failure is None


def test_successful_retry_and_conflicting_immutable_evidence() -> None:
    store = prepared_store()
    original = evidence(store)
    assert finalize(store, original).failure is None
    after = store.snapshot()
    assert finalize(store, original).failure is None
    assert (
        finalize(store, replace(original, expected_attention_revision=after.revision)).failure
        is None
    )
    assert store.snapshot() is after
    for changes in (
        {"source_decision_id": "other-decision"},
        {"source_event_ids": ("user-b",)},
        {"completed_at": original.completed_at + timedelta(seconds=1)},
    ):
        conflicting = replace(original, **changes)
        assert conflicting.settlement_id == original.settlement_id
        assert finalize(store, conflicting).failure is FinalizationFailure.TARGET_REJECTED
        assert store.snapshot() is after


@pytest.mark.parametrize("foreground", ["user-a", "other"])
def test_atomic_cleanup_preserves_unrelated_focus_and_fairness(foreground: str) -> None:
    store = prepared_store()
    assert store.claim_next(0, NOW + timedelta(seconds=24)) is not None
    assert store.claim_next(0, NOW + timedelta(seconds=25)) is not None
    state = store.snapshot()
    assert state.cooldowns and state.last_selected_epochs
    store.apply(
        1,
        (
            transition(
                Op.ACQUIRE_FOREGROUND,
                state.revision,
                1,
                target_ref=foreground,
                source_intent_ref="focus-intent",
            ),
            transition(
                Op.ADD_MONITOR,
                state.revision,
                1,
                target_ref="user-a" if foreground == "other" else "other",
            ),
            transition(Op.ADD_MONITOR, state.revision, 1, target_ref="user-b"),
        ),
    )
    before = store.snapshot()
    assert finalize(store, evidence(store)).failure is None
    after = store.snapshot()
    assert after.secondary_monitor_refs == (
        ("other", "user-b") if foreground == "user-a" else ("user-b",)
    )
    assert after.foreground_focus_ref == (None if foreground == "user-a" else "other")
    assert after.active_focus_intent_ref == (None if foreground == "user-a" else "focus-intent")
    assert all(ref != "user-a" for ref, _ in after.last_selected_epochs)
    assert all(item.source_ref != "user-a" for item in after.cooldowns)
    assert after.last_selected_priority == before.last_selected_priority
    assert after.priority_burst == before.priority_burst
    assert after.selection_epoch == before.selection_epoch
    assert after.updated_at >= before.updated_at


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("observed_execution_id", " "),
        ("latest_observation_id", ""),
        ("source_decision_id", None),
        ("observed_record_revision", True),
        ("expected_attention_revision", -1),
        ("expected_source_context_revision", 1.5),
        ("source_event_ids", ()),
        ("source_event_ids", ("a", "a")),
        ("source_event_ids", ("",)),
        ("source_event_ids", ["a"]),
        ("completed_at", NOW.replace(tzinfo=None)),
    ],
)
def test_evidence_strict_validation(field: str, invalid: Any) -> None:
    with pytest.raises(ValueError):
        evidence(prepared_store(), **{field: invalid})


def test_identity_is_deterministic_and_observation_specific() -> None:
    store = prepared_store()
    a = evidence(store)
    assert evidence(store).settlement_id == a.settlement_id
    assert replace(a, expected_attention_revision=999).settlement_id == a.settlement_id
    for changes in (
        {"observed_execution_id": "other"},
        {"observed_record_revision": 3},
        {"latest_observation_id": "other"},
    ):
        assert replace(a, **changes).settlement_id != a.settlement_id


def test_invalid_runtime_payload_does_not_poison_owner() -> None:
    store = prepared_store()
    before = store.snapshot()
    invalid: Any = "invalid"
    assert finalize(store, invalid).failure is FinalizationFailure.TARGET_REJECTED
    assert store.snapshot() is before
    assert finalize(store, evidence(store)).failure is None


def test_retry_keeps_later_turn_and_obligation_unchanged() -> None:
    store = prepared_store()
    original = evidence(store)
    assert finalize(store, original).failure is None
    state = store.snapshot()
    store.apply(
        1,
        tuple(
            replace(
                transition(op, state.revision, 1, value="user-b"),
                occurred_at=state.updated_at + timedelta(seconds=1),
            )
            for op in (Op.ASSIGN_TURN, Op.SET_RESPONSE_OBLIGATION)
        ),
    )
    later = store.snapshot()
    assert finalize(store, original).failure is None
    assert store.snapshot() is later
    assert later.current_turn_owner == later.response_obligation == "user-b"
