import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.executive import (
    CommitmentTransitionIntent,
    CommitmentTransitionOperation,
    CommitmentTransitionPayload,
    CommittedExecutiveDecision,
    ExecutiveDecisionCandidate,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePriority,
    GoalTransitionIntent,
    GoalTransitionOperation,
    GoalTransitionPayload,
)
from app.domain.goals import (
    AutonomyTriggerKind,
    CommitmentStatus,
    GoalCommitmentStore,
    GoalStatus,
    autonomy_triggers,
    build_goal_context_view,
)

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def decision(
    decision_id: str,
    revision: int,
    *,
    goals: tuple[GoalTransitionIntent, ...] = (),
    commitments: tuple[CommitmentTransitionIntent, ...] = (),
) -> CommittedExecutiveDecision:
    candidate = ExecutiveDecisionCandidate(
        f"candidate-{decision_id}",
        f"trigger-{decision_id}",
        (f"event-{decision_id}",),
        1,
        revision,
        1,
        ExecutiveOutcome.CONTINUE_ACTIVITY,
        ExecutivePriority.NORMAL,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (),
        goals,
        commitments,
        (f"event-{decision_id}",),
        NOW + timedelta(seconds=revision),
    )
    return CommittedExecutiveDecision(
        decision_id,
        candidate,
        (),
        NOW + timedelta(seconds=revision),
    )


def goal_transition(
    operation: GoalTransitionOperation,
    revision: int,
    *,
    goal_id: str = "goal-1",
    superseding_goal_ref: str | None = None,
) -> GoalTransitionIntent:
    if operation is GoalTransitionOperation.CREATE:
        return GoalTransitionIntent(
            f"goal-intent-{operation.value}-{revision}",
            operation,
            None,
            goal_id,
            revision,
            GoalTransitionPayload(
                f"semantic-{goal_id}",
                60,
                goal_kind="social",
                target_ref=f"target-{goal_id}",
                precondition_ids=(f"pre-{goal_id}",),
                completion_condition_refs=(f"complete-{goal_id}",),
                interruption_policy="protected",
            ),
            (f"reason-{goal_id}",),
        )
    payload = GoalTransitionPayload(
        priority=80 if operation is GoalTransitionOperation.REPRIORITIZE else None,
        superseding_goal_ref=superseding_goal_ref
        if operation is GoalTransitionOperation.SUPERSEDE
        else None,
    )
    return GoalTransitionIntent(
        f"goal-intent-{operation.value}-{revision}",
        operation,
        goal_id,
        None,
        revision,
        payload,
        (f"reason-{goal_id}",),
    )


def commitment_transition(
    operation: CommitmentTransitionOperation,
    revision: int,
    *,
    commitment_id: str = "commitment-1",
) -> CommitmentTransitionIntent:
    return CommitmentTransitionIntent(
        f"commitment-intent-{operation.value}-{revision}",
        operation,
        None if operation is CommitmentTransitionOperation.CREATE else commitment_id,
        commitment_id if operation is CommitmentTransitionOperation.CREATE else None,
        revision,
        CommitmentTransitionPayload(
            f"semantic-{commitment_id}"
            if operation is CommitmentTransitionOperation.CREATE
            else None,
            counterparty_ref=f"counterparty-{commitment_id}"
            if operation is CommitmentTransitionOperation.CREATE
            else None,
            related_goal_refs=(),
            strength=70 if operation is CommitmentTransitionOperation.CREATE else None,
            priority=65 if operation is CommitmentTransitionOperation.CREATE else None,
            due_condition_refs=(f"due-{commitment_id}",)
            if operation is CommitmentTransitionOperation.CREATE
            else (),
            release_condition_refs=(f"release-{commitment_id}",)
            if operation is CommitmentTransitionOperation.CREATE
            else (),
        ),
        (f"reason-{commitment_id}",),
    )


def apply_goal(
    store: GoalCommitmentStore,
    operation: GoalTransitionOperation,
    revision: int,
    *,
    goal_id: str = "goal-1",
    superseding_goal_ref: str | None = None,
) -> None:
    transition = goal_transition(
        operation,
        revision,
        goal_id=goal_id,
        superseding_goal_ref=superseding_goal_ref,
    )
    store.apply(
        decision(f"goal-{operation.value}-{revision}-{goal_id}", revision, goals=(transition,))
    )


def apply_commitment(
    store: GoalCommitmentStore,
    operation: CommitmentTransitionOperation,
    revision: int,
    *,
    commitment_id: str = "commitment-1",
) -> None:
    transition = commitment_transition(operation, revision, commitment_id=commitment_id)
    store.apply(
        decision(
            f"commitment-{operation.value}-{revision}-{commitment_id}",
            revision,
            commitments=(transition,),
        )
    )


def test_goal_lifecycle_create_activate_suspend_resume_complete() -> None:
    store = GoalCommitmentStore()
    for revision, operation in enumerate(
        (
            GoalTransitionOperation.CREATE,
            GoalTransitionOperation.ACTIVATE,
            GoalTransitionOperation.SUSPEND,
            GoalTransitionOperation.RESUME,
            GoalTransitionOperation.COMPLETE,
        )
    ):
        apply_goal(store, operation, revision)
    goal = store.snapshot().goals[0]
    assert goal.status is GoalStatus.COMPLETED
    assert goal.revision == 5
    assert goal.kind.value == "social"
    assert goal.target_ref == "target-goal-1"
    assert goal.precondition_ids == ("pre-goal-1",)
    assert goal.completion_condition_refs == ("complete-goal-1",)
    assert goal.interruption_policy.value == "protected"


@pytest.mark.parametrize(
    "terminal",
    [GoalTransitionOperation.ABANDON, GoalTransitionOperation.COMPLETE],
)
def test_terminal_goal_rejects_further_transition(terminal: GoalTransitionOperation) -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0)
    if terminal is GoalTransitionOperation.COMPLETE:
        apply_goal(store, GoalTransitionOperation.ACTIVATE, 1)
        revision = 2
    else:
        revision = 1
    apply_goal(store, terminal, revision)
    with pytest.raises(ValueError, match="terminal|illegal"):
        apply_goal(store, GoalTransitionOperation.REPRIORITIZE, revision + 1)


def test_goal_reprioritize_and_supersede_require_valid_state() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0, goal_id="goal-old")
    apply_goal(store, GoalTransitionOperation.CREATE, 1, goal_id="goal-new")
    apply_goal(store, GoalTransitionOperation.REPRIORITIZE, 2, goal_id="goal-old")
    assert (
        next(item for item in store.snapshot().goals if item.goal_id == "goal-old").priority == 80
    )
    apply_goal(
        store,
        GoalTransitionOperation.SUPERSEDE,
        3,
        goal_id="goal-old",
        superseding_goal_ref="goal-new",
    )
    assert (
        next(item for item in store.snapshot().goals if item.goal_id == "goal-old").status
        is GoalStatus.SUPERSEDED
    )


def test_active_goal_can_fail_only_through_executive_transition() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0)
    apply_goal(store, GoalTransitionOperation.ACTIVATE, 1)
    apply_goal(store, GoalTransitionOperation.FAIL, 2)
    assert store.snapshot().goals[0].status is GoalStatus.FAILED


def test_commitment_lifecycle_and_duplicate_rejection() -> None:
    store = GoalCommitmentStore()
    for revision, operation in enumerate(
        (
            CommitmentTransitionOperation.CREATE,
            CommitmentTransitionOperation.ACTIVATE,
            CommitmentTransitionOperation.SUSPEND,
            CommitmentTransitionOperation.RESUME,
            CommitmentTransitionOperation.FULFILL,
        )
    ):
        apply_commitment(store, operation, revision)
    assert store.snapshot().commitments[0].status is CommitmentStatus.FULFILLED
    assert store.snapshot().commitments[0].counterparty_ref == "counterparty-commitment-1"
    assert store.snapshot().commitments[0].strength == 70
    assert store.snapshot().commitments[0].priority == 65
    assert store.snapshot().commitments[0].due_condition_refs == ("due-commitment-1",)
    duplicate = commitment_transition(CommitmentTransitionOperation.CREATE, 5)
    with pytest.raises(ValueError, match="already exists"):
        store.apply(decision("duplicate", 5, commitments=(duplicate,)))
    assert store.snapshot().revision == 5


def test_duplicate_active_commitment_semantic_spec_with_different_id_is_rejected() -> None:
    store = GoalCommitmentStore()
    first = commitment_transition(
        CommitmentTransitionOperation.CREATE, 0, commitment_id="commitment-a"
    )
    store.apply(decision("first", 0, commitments=(first,)))
    second = commitment_transition(
        CommitmentTransitionOperation.CREATE, 1, commitment_id="commitment-b"
    )
    second = replace(
        second,
        payload=replace(
            second.payload,
            semantic_commitment_ref=first.payload.semantic_commitment_ref,
            counterparty_ref=first.payload.counterparty_ref,
            due_condition_refs=first.payload.due_condition_refs,
            release_condition_refs=first.payload.release_condition_refs,
        ),
    )
    with pytest.raises(ValueError, match="duplicate active commitment"):
        store.apply(decision("second", 1, commitments=(second,)))


def test_commitment_can_link_existing_goal_through_typed_transition() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0)
    transition = commitment_transition(CommitmentTransitionOperation.CREATE, 1)
    transition = replace(
        transition,
        payload=replace(transition.payload, related_goal_refs=("goal-1",)),
    )
    store.apply(decision("linked-commitment", 1, commitments=(transition,)))
    assert store.snapshot().commitments[0].related_goal_refs == ("goal-1",)


def test_initial_snapshot_and_candidate_transition_revision_are_strict() -> None:
    with pytest.raises(ValueError, match="initial"):
        GoalCommitmentStore("not-snapshot")  # type: ignore[arg-type]
    mismatched = goal_transition(GoalTransitionOperation.CREATE, 1)
    with pytest.raises(ValueError, match="candidate goal_revision"):
        decision("mismatched", 0, goals=(mismatched,))


def test_stale_and_duplicate_decision_are_rejected() -> None:
    store = GoalCommitmentStore()
    first = decision("decision-1", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),))
    store.apply(first)
    with pytest.raises(ValueError, match="already applied"):
        store.apply(first)
    stale = decision(
        "decision-stale",
        0,
        goals=(goal_transition(GoalTransitionOperation.ACTIVATE, 0),),
    )
    with pytest.raises(ValueError, match="stale"):
        store.apply(stale)


def test_multi_transition_batch_is_all_or_nothing() -> None:
    store = GoalCommitmentStore()
    create = goal_transition(GoalTransitionOperation.CREATE, 0)
    invalid = goal_transition(
        GoalTransitionOperation.ACTIVATE,
        0,
        goal_id="missing-goal",
    )
    with pytest.raises(ValueError, match="does not exist"):
        store.apply(decision("batch-invalid", 0, goals=(create, invalid)))
    assert store.snapshot().revision == 0
    assert store.snapshot().goals == ()


def test_competing_same_revision_batches_commit_only_once() -> None:
    store = GoalCommitmentStore()

    def attempt(index: int) -> str:
        value = decision(
            f"decision-{index}",
            0,
            goals=(
                goal_transition(
                    GoalTransitionOperation.CREATE,
                    0,
                    goal_id=f"goal-{index}",
                ),
            ),
        )
        try:
            store.apply(value)
            return "committed"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, range(2)))
    assert results.count("committed") == 1
    assert results.count("rejected") == 1
    assert store.snapshot().revision == 1


def test_snapshot_persists_across_turns_and_is_json_serializable() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0)
    turn_one = store.snapshot()
    turn_two = store.snapshot()
    assert turn_two == turn_one
    json.dumps(turn_two.to_dict(), allow_nan=False)


def test_bounded_view_orders_by_priority_and_excludes_terminal_state() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0, goal_id="low")
    apply_goal(store, GoalTransitionOperation.CREATE, 1, goal_id="high")
    apply_goal(store, GoalTransitionOperation.ACTIVATE, 2, goal_id="low")
    apply_goal(store, GoalTransitionOperation.ACTIVATE, 3, goal_id="high")
    apply_goal(store, GoalTransitionOperation.REPRIORITIZE, 4, goal_id="high")
    view = build_goal_context_view(store.snapshot(), max_active=1, max_recent=1)
    assert [item.goal_id for item in view.active_goals] == ["high"]
    assert view.goal_revision == store.snapshot().revision
    assert len(view.recently_changed_goals) == 1


def test_autonomy_triggers_return_to_executive_without_action() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0)
    apply_commitment(store, CommitmentTransitionOperation.CREATE, 1)
    triggers = autonomy_triggers(store.snapshot())
    assert {item.kind for item in triggers} == {
        AutonomyTriggerKind.PENDING_GOAL,
        AutonomyTriggerKind.COMMITMENT_DUE_CHECK,
    }
    assert all(not hasattr(item, "action") for item in triggers)
