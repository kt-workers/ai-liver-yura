"""定型評価と注意の実所有者を結び、選択元と現在状態の由来を検証する。"""

import asyncio
from dataclasses import replace

import pytest

from app.composition.attention import CoreAttentionBinding
from app.domain.appraisal import DeterministicAppraisalRule, StateDeltaProposal
from app.domain.attention import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionSchedulingPolicy,
    AttentionSourceKind,
    AttentionTurnStore,
)
from app.domain.contracts import RevisionVector
from app.domain.executive import GoalTransitionOperation
from tests.domain.appraisal.test_appraisal_paths import JOY
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.system_integration.test_core_appraisal import Port, Setup, setup


def rules() -> tuple[DeterministicAppraisalRule, ...]:
    return (
        DeterministicAppraisalRule(
            "activity-result",
            "activity.completed",
            (),
            (StateDeltaProposal(JOY, 0.1, 0.8, ("event:1",)),),
            0.7,
            0.8,
        ),
    )


def connect(value: Setup) -> tuple[CoreAttentionBinding, AttentionTurnStore]:
    attention = AttentionTurnStore(AttentionSchedulingPolicy.production())
    return CoreAttentionBinding(value.connection, attention, value.clock), attention


def test_fast_evaluation_reaches_attention_without_llm_or_forced_decision() -> None:
    value = setup()
    connection, owner = connect(value)
    committed = value.connection.appraise_fast(value.event, rules(), candidate_id="fast")
    assert committed is not None
    assert not value.port.requests
    offered = connection.offer_appraisal()
    assert offered.selection_epoch == 0
    dispatch = connection.claim_next()
    assert dispatch is not None
    assert dispatch.selected_appraisal is committed
    assert dispatch.current_appraisal is committed
    assert dispatch.selected_source.source_revision == committed.candidate.base_state_revision
    assert dispatch.current_appraisal.internal_state.revision == 4
    assert dispatch.trigger.attention_revision == owner.snapshot().revision
    assert dispatch.trigger.goal_revision == value.goals.snapshot().revision
    assert connection.is_current(dispatch)
    assert not connection.is_current(
        replace(dispatch, trigger=replace(dispatch.trigger, trigger_id="forged"))
    )
    again = connection.claim_next()
    assert again is not None and again.trigger.trigger_id != dispatch.trigger.trigger_id
    assert not connection.is_current(dispatch)
    assert connection.is_current(again)


def test_fast_rule_absence_and_rejection_do_not_replace_success() -> None:
    value = setup()
    first = value.connection.appraise_fast(value.event, rules(), candidate_id="first")
    assert first is not None
    assert value.connection.appraise_fast(value.event, (), candidate_id="none") is None
    assert value.connection.latest_commit() is first
    with pytest.raises(ValueError, match="現在の参照文脈"):
        value.connection.appraise_fast(
            replace(value.event, revisions=RevisionVector(0)),
            rules(),
            candidate_id="stale",
        )
    assert value.connection.current_commit() is first
    assert not value.port.requests


@pytest.mark.asyncio
async def test_fast_commit_rejects_waiting_deep_and_shares_facts_sequence() -> None:
    value = setup(Port(waiting=True))
    task = asyncio.create_task(value.appraise())
    await asyncio.wait_for(value.port.started.wait(), 1)
    fast = value.connection.appraise_fast(value.event, rules(), candidate_id="fast")
    value.port.release.set()
    with pytest.raises(ValueError, match="stale state"):
        await task
    assert value.connection.current_commit() is fast
    deep = await value.appraise("next")
    assert fast is not None
    assert deep.appraisal_facts.revision == fast.appraisal_facts.revision + 1


def offer_user(owner: AttentionTurnStore, value: Setup, revision: int = 1) -> None:
    owner.offer(
        AttentionIngressSignal(
            "input-offer",
            AttentionIngressOperation.OFFER,
            "user-event",
            AttentionSourceKind.USER_INTERACTION,
            revision,
            value.clock.now(),
            trusted_direct_user=True,
        )
    )


def test_direct_user_selection_does_not_relabel_latest_appraisal_as_its_origin() -> None:
    value = setup()
    connection, owner = connect(value)
    committed = value.connection.appraise_fast(value.event, rules(), candidate_id="fast")
    connection.offer_appraisal()
    offer_user(owner, value)
    dispatch = connection.claim_next()
    assert dispatch is not None
    assert dispatch.selected_source.source_ref == "user-event"
    assert dispatch.current_appraisal is committed
    assert dispatch.selected_appraisal is None
    assert connection.is_current(dispatch)


def test_attention_can_select_without_deep_or_any_appraisal() -> None:
    value = setup()
    connection, owner = connect(value)
    offer_user(owner, value)
    dispatch = connection.claim_next()
    assert dispatch is not None
    assert dispatch.current_appraisal is None
    assert dispatch.selected_appraisal is None
    assert not value.port.requests
    assert value.owner.snapshot().revision == 3


def test_old_source_origin_is_preserved_separately_from_current_context() -> None:
    value = setup()
    connection, owner = connect(value)
    offer_user(owner, value, revision=0)
    value.connection.appraise_fast(value.event, rules(), candidate_id="fast")
    connection.offer_appraisal()
    dispatch = connection.claim_next()
    assert dispatch is not None
    assert dispatch.selected_source.source_ref == "user-event"
    assert dispatch.selected_source.source_context_revision == 0
    assert dispatch.trigger.source_context_revision == 1
    assert dispatch.reference.context.source_context_revision == 1
    assert dispatch.selected_appraisal is None


def test_stale_attention_context_is_not_claimed_or_rewritten() -> None:
    value = setup()
    connection, owner = connect(value)
    value.connection.appraise_fast(value.event, rules(), candidate_id="first")
    connection.offer_appraisal()
    before = owner.snapshot()
    apply_goal(value.goals, GoalTransitionOperation.CREATE, 0)
    with pytest.raises(ValueError, match="注意の文脈"):
        connection.claim_next()
    with pytest.raises(ValueError, match="現在の確定済み評価"):
        connection.offer_appraisal()
    assert owner.snapshot() is before
    value.event = replace(value.event, revisions=RevisionVector(2))
    value.connection.appraise_fast(value.event, rules(), candidate_id="next")
    connection.offer_appraisal()
    dispatch = connection.claim_next()
    assert dispatch is not None
    assert dispatch.trigger.goal_revision == value.goals.snapshot().revision


@pytest.mark.parametrize("changed", ["goal", "appraisal", "attention"])
def test_dispatch_currentness_rechecks_each_owner(changed: str) -> None:
    value = setup()
    connection, owner = connect(value)
    value.connection.appraise_fast(value.event, rules(), candidate_id="first")
    connection.offer_appraisal()
    dispatch = connection.claim_next()
    assert dispatch is not None and connection.is_current(dispatch)
    if changed == "goal":
        apply_goal(value.goals, GoalTransitionOperation.CREATE, 0)
    elif changed == "appraisal":
        value.connection.appraise_fast(value.event, rules(), candidate_id="next")
    else:
        offer_user(owner, value)
    assert not connection.is_current(dispatch)


def test_state_change_without_appraisal_facts_invalidates_dispatch() -> None:
    from app.domain.appraisal import appraise_event

    value = setup()
    connection, owner = connect(value)
    offer_user(owner, value)
    dispatch = connection.claim_next()
    assert dispatch is not None and dispatch.current_appraisal is None
    candidate = appraise_event(
        value.event,
        value.owner.snapshot(),
        rules(),
        candidate_id="external",
        created_at=value.clock.now(),
    )
    assert candidate is not None
    value.owner.commit(candidate, current_source_context_revision=1, committed_at=value.clock.now())
    assert value.connection.current_commit() is None
    assert not connection.is_current(dispatch)
    assert dispatch.current_state.revision == 3
