import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import SourceLifecycleOperation
from app.domain.executive import (
    CommitmentTransitionIntent,
    CommitmentTransitionOperation,
    CommitmentTransitionPayload,
    CommittedExecutiveDecision,
    ExecutiveBoundsProvenance,
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
    CommitmentLifecycleProjectionFact,
    CommitmentState,
    CommitmentStatus,
    DueCommitmentOrder,
    GoalCommitmentCommitResult,
    GoalCommitmentSnapshot,
    GoalCommitmentStore,
    GoalContextBuildError,
    GoalContextFailureCode,
    GoalContextView,
    GoalKind,
    GoalLifecycleProjectionFact,
    GoalState,
    GoalStatus,
    InterruptionPolicy,
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
        ExecutiveBoundsProvenance("test-bounds", 1),
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
) -> GoalCommitmentCommitResult:
    transition = goal_transition(
        operation,
        revision,
        goal_id=goal_id,
        superseding_goal_ref=superseding_goal_ref,
    )
    return store.apply(
        decision(f"goal-{operation.value}-{revision}-{goal_id}", revision, goals=(transition,))
    )


def apply_commitment(
    store: GoalCommitmentStore,
    operation: CommitmentTransitionOperation,
    revision: int,
    *,
    commitment_id: str = "commitment-1",
) -> GoalCommitmentCommitResult:
    transition = commitment_transition(operation, revision, commitment_id=commitment_id)
    return store.apply(
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


def test_goal_and_commitment_owner_facts_carry_open_refresh_and_close_cas() -> None:
    store = GoalCommitmentStore()
    opened = apply_goal(store, GoalTransitionOperation.CREATE, 0).lifecycle_facts
    assert len(opened) == 1
    assert opened[0].operation is SourceLifecycleOperation.OPEN
    assert opened[0].expected_source_revision is None
    refreshed = apply_goal(store, GoalTransitionOperation.ACTIVATE, 1).lifecycle_facts
    assert len(refreshed) == 1
    assert refreshed[0].operation is SourceLifecycleOperation.REFRESH
    assert refreshed[0].expected_source_revision == 1
    closed = apply_goal(store, GoalTransitionOperation.COMPLETE, 2).lifecycle_facts
    assert len(closed) == 1
    assert closed[0].operation is SourceLifecycleOperation.CLOSE
    assert closed[0].expected_source_revision == 2

    commitment_store = GoalCommitmentStore()
    opened_commitment = apply_commitment(commitment_store, CommitmentTransitionOperation.CREATE, 0)
    assert opened_commitment.lifecycle_facts[0].operation is SourceLifecycleOperation.OPEN
    refreshed_commitment = apply_commitment(
        commitment_store, CommitmentTransitionOperation.ACTIVATE, 1
    )
    assert refreshed_commitment.lifecycle_facts[0].operation is SourceLifecycleOperation.REFRESH
    closed_commitment = apply_commitment(commitment_store, CommitmentTransitionOperation.RELEASE, 2)
    assert closed_commitment.lifecycle_facts[0].operation is SourceLifecycleOperation.CLOSE


def test_goal_and_commitment_lifecycle_operation_status_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="terminal Goal"):
        GoalLifecycleProjectionFact(
            "goal-close-active",
            "goal-1",
            SourceLifecycleOperation.CLOSE,
            2,
            1,
            GoalStatus.ACTIVE,
            50,
            2,
            NOW,
        )
    with pytest.raises(ValueError, match="terminal Goal"):
        GoalLifecycleProjectionFact(
            "goal-refresh-completed",
            "goal-1",
            SourceLifecycleOperation.REFRESH,
            2,
            1,
            GoalStatus.COMPLETED,
            50,
            2,
            NOW,
        )
    with pytest.raises(ValueError, match="terminal Commitment"):
        CommitmentLifecycleProjectionFact(
            "commitment-close-active",
            "commitment-1",
            SourceLifecycleOperation.CLOSE,
            2,
            1,
            CommitmentStatus.ACTIVE,
            50,
            2,
            NOW,
        )


def test_goal_commit_results_keep_each_commit_output_without_owner_history() -> None:
    store = GoalCommitmentStore()
    opened = apply_goal(store, GoalTransitionOperation.CREATE, 0)
    refreshed = apply_goal(store, GoalTransitionOperation.ACTIVATE, 1)
    assert opened.lifecycle_facts[0].operation is SourceLifecycleOperation.OPEN
    assert refreshed.lifecycle_facts[0].operation is SourceLifecycleOperation.REFRESH
    assert opened.snapshot.revision == 1
    assert store.snapshot().revision == 2
    with pytest.raises(ValueError):
        store.apply(decision("invalid-empty", 2))
    assert store.snapshot().revision == 2
    assert not hasattr(store, "lifecycle_facts")


def test_goal_create_rejects_dangling_commitment_reference_atomically() -> None:
    store = GoalCommitmentStore()
    transition = goal_transition(GoalTransitionOperation.CREATE, 0)
    transition = replace(
        transition,
        payload=replace(transition.payload, commitment_refs=("commitment-missing",)),
    )
    with pytest.raises(ValueError, match="commitment reference"):
        store.apply(decision("decision-dangling", 0, goals=(transition,)))
    assert store.snapshot().revision == 0
    assert store.snapshot().goals == ()


def test_goal_may_reference_commitment_created_in_same_atomic_batch() -> None:
    store = GoalCommitmentStore()
    goal = goal_transition(GoalTransitionOperation.CREATE, 0)
    goal = replace(goal, payload=replace(goal.payload, commitment_refs=("commitment-1",)))
    commitment = commitment_transition(CommitmentTransitionOperation.CREATE, 0)
    result = store.apply(
        decision("decision-same-batch", 0, goals=(goal,), commitments=(commitment,))
    )
    assert result.snapshot.goals[0].commitment_refs == ("commitment-1",)
    assert result.snapshot.commitments[0].commitment_id == "commitment-1"


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


def test_duplicate_commitment_spec_is_order_independent() -> None:
    store = GoalCommitmentStore()
    apply_goal(store, GoalTransitionOperation.CREATE, 0, goal_id="goal-a")
    apply_goal(store, GoalTransitionOperation.CREATE, 1, goal_id="goal-b")
    first = commitment_transition(
        CommitmentTransitionOperation.CREATE, 2, commitment_id="commitment-a"
    )
    first = replace(
        first,
        payload=replace(
            first.payload,
            related_goal_refs=("goal-a", "goal-b"),
            due_condition_refs=("due-a", "due-b"),
            release_condition_refs=("release-a", "release-b"),
        ),
    )
    store.apply(decision("first-ordered", 2, commitments=(first,)))
    second = commitment_transition(
        CommitmentTransitionOperation.CREATE, 3, commitment_id="commitment-b"
    )
    second = replace(
        second,
        payload=replace(
            second.payload,
            semantic_commitment_ref=first.payload.semantic_commitment_ref,
            counterparty_ref=first.payload.counterparty_ref,
            related_goal_refs=("goal-b", "goal-a"),
            due_condition_refs=("due-b", "due-a"),
            release_condition_refs=("release-b", "release-a"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate active commitment"):
        store.apply(decision("second-reordered", 3, commitments=(second,)))


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
    view = build_goal_context_view(store.snapshot())
    assert [item.goal_id for item in view.active_goals] == ["high", "low"]
    assert view.goal_revision == store.snapshot().revision
    assert view.policy_id == V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_id


def _goal(
    goal_id: str,
    status: GoalStatus,
    priority: int,
    updated_at: datetime,
    *,
    refs: int = 0,
) -> GoalState:
    return GoalState(
        goal_id,
        GoalKind.SOCIAL,
        f"semantic-{goal_id}",
        None,
        "decision-1",
        status,
        priority,
        tuple(f"motivation-{index}" for index in range(refs)),
        (),
        (),
        (),
        InterruptionPolicy.INTERRUPTIBLE,
        NOW,
        updated_at,
        1,
    )


def _commitment(
    commitment_id: str,
    status: CommitmentStatus,
    priority: int,
    updated_at: datetime,
    *,
    refs: int = 0,
) -> CommitmentState:
    return CommitmentState(
        commitment_id,
        f"semantic-{commitment_id}",
        None,
        ("event-1",),
        "decision-1",
        (),
        status,
        50,
        priority,
        tuple(f"due-{index}" for index in range(refs)),
        (),
        NOW,
        updated_at,
        1,
    )


def _snapshot(
    goals: tuple[GoalState, ...] = (), commitments: tuple[CommitmentState, ...] = ()
) -> GoalCommitmentSnapshot:
    return GoalCommitmentSnapshot(1, goals, commitments, NOW + timedelta(days=2))


def test_bounded_view_uses_policy_provenance_and_goal_ordering() -> None:
    later = NOW + timedelta(hours=2)
    snapshot = _snapshot(
        (
            _goal("goal-b", GoalStatus.ACTIVE, 70, NOW),
            _goal("goal-a", GoalStatus.ACTIVE, 70, NOW),
            _goal("goal-later", GoalStatus.ACTIVE, 70, later),
            _goal("suspended-b", GoalStatus.SUSPENDED, 60, NOW),
            _goal("suspended-a", GoalStatus.SUSPENDED, 60, NOW),
        )
    )
    view = build_goal_context_view(snapshot)
    assert view.policy_id == V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_id
    assert view.policy_revision == V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision
    assert [item.goal_id for item in view.active_goals] == ["goal-later", "goal-a", "goal-b"]
    assert [item.goal_id for item in view.suspended_goals] == ["suspended-a", "suspended-b"]


def test_bounded_view_selects_due_then_active_and_excludes_unrelated() -> None:
    snapshot = _snapshot(
        commitments=(
            _commitment("due", CommitmentStatus.PROPOSED, 1, NOW),
            _commitment("active-low", CommitmentStatus.ACTIVE, 10, NOW),
            _commitment("active-high", CommitmentStatus.ACTIVE, 90, NOW),
            _commitment("suspended", CommitmentStatus.SUSPENDED, 100, NOW),
            _commitment("terminal", CommitmentStatus.FULFILLED, 100, NOW),
        )
    )
    view = build_goal_context_view(snapshot, due_order=DueCommitmentOrder(1, ("due",)))
    assert [item.commitment_id for item in view.commitments] == ["due", "active-high", "active-low"]


def test_bounded_view_fallback_commitment_order_uses_updated_at_then_id() -> None:
    later = NOW + timedelta(hours=1)
    snapshot = _snapshot(
        commitments=(
            _commitment("commitment-b", CommitmentStatus.ACTIVE, 10, NOW),
            _commitment("commitment-a", CommitmentStatus.ACTIVE, 10, NOW),
            _commitment("commitment-later", CommitmentStatus.ACTIVE, 10, later),
        )
    )
    view = build_goal_context_view(snapshot)
    assert [item.commitment_id for item in view.commitments] == [
        "commitment-later",
        "commitment-a",
        "commitment-b",
    ]


def test_recent_changes_are_selected_once_across_goal_and_commitment() -> None:
    at_same_time = NOW + timedelta(hours=1)
    snapshot = _snapshot(
        (
            _goal("goal-b", GoalStatus.ACTIVE, 1, at_same_time),
            _goal("goal-a", GoalStatus.ACTIVE, 1, at_same_time),
        ),
        (_commitment("commitment-a", CommitmentStatus.ACTIVE, 1, at_same_time),),
    )
    policy = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        goal_context=replace(
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.goal_context,
            max_recently_changed_items=2,
        ),
    )
    view = build_goal_context_view(snapshot, bounds_policy=policy)
    assert [item.goal_id for item in view.recently_changed_goals] == ["goal-a", "goal-b"]
    assert view.recently_changed_commitments == ()


@pytest.mark.parametrize("status", [GoalStatus.ACTIVE, GoalStatus.SUSPENDED])
@pytest.mark.parametrize("count", [32, 33])
def test_goal_section_count_bounds(status: GoalStatus, count: int) -> None:
    goals = tuple(_goal(f"goal-{index}", status, 1, NOW) for index in range(count))
    view = build_goal_context_view(_snapshot(goals))
    selected = view.active_goals if status is GoalStatus.ACTIVE else view.suspended_goals
    assert len(selected) == 32


@pytest.mark.parametrize("count", [64, 65])
def test_commitment_and_recent_count_bounds(count: int) -> None:
    commitments = tuple(
        _commitment(f"commitment-{index}", CommitmentStatus.ACTIVE, 1, NOW)
        for index in range(count)
    )
    view = build_goal_context_view(_snapshot(commitments=commitments))
    assert len(view.commitments) == min(count, 64)
    assert len(view.recently_changed_goals) + len(view.recently_changed_commitments) == min(
        count, 64
    )


@pytest.mark.parametrize(
    ("is_goal", "refs", "too_large"),
    [(True, 64, False), (True, 65, True), (False, 63, False), (False, 64, True)],
)
def test_reference_bounds_fail_closed_without_mutation(
    is_goal: bool, refs: int, too_large: bool
) -> None:
    snapshot = (
        _snapshot(goals=(_goal("goal-1", GoalStatus.ACTIVE, 1, NOW, refs=refs),))
        if is_goal
        else _snapshot(
            commitments=(_commitment("commitment-1", CommitmentStatus.ACTIVE, 1, NOW, refs=refs),)
        )
    )
    before = snapshot.to_dict()
    if too_large:
        with pytest.raises(GoalContextBuildError) as error:
            build_goal_context_view(snapshot)
        assert error.value.code is GoalContextFailureCode.ITEM_TOO_LARGE
    else:
        build_goal_context_view(snapshot)
    assert snapshot.to_dict() == before


def test_goal_context_view_rejects_duplicates_within_a_section() -> None:
    goal = _goal("goal-1", GoalStatus.ACTIVE, 1, NOW)
    with pytest.raises(ValueError, match="重複"):
        GoalContextView(1, "policy", 1, (goal, goal), (), (), (), ())


def test_goal_context_view_allows_same_goal_across_sections() -> None:
    goal = _goal("goal-1", GoalStatus.ACTIVE, 1, NOW)
    view = GoalContextView(1, "policy", 1, (goal,), (), (), (goal,), ())
    assert view.active_goals == view.recently_changed_goals


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
