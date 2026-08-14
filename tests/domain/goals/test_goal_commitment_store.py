import json
from concurrent.futures import ThreadPoolExecutor
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
            GoalTransitionPayload(f"semantic-{goal_id}", 60),
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
            else None
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
    duplicate = commitment_transition(CommitmentTransitionOperation.CREATE, 5)
    with pytest.raises(ValueError, match="already exists"):
        store.apply(decision("duplicate", 5, commitments=(duplicate,)))
    assert store.snapshot().revision == 5


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
    view = build_goal_context_view(store.snapshot(), max_active=1)
    assert [item.goal_id for item in view.active_goals] == ["high"]
    assert view.goal_revision == store.snapshot().revision


def test_autonomy_triggers_return_to_executive_without_action() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0)
    apply_commitment(store, CommitmentTransitionOperation.CREATE, 1)
    triggers = autonomy_triggers(store.snapshot())
    assert {item.kind for item in triggers} == {
        AutonomyTriggerKind.PENDING_GOAL,
        AutonomyTriggerKind.COMMITMENT_REVIEW,
    }
    assert all(not hasattr(item, "action") for item in triggers)
