from __future__ import annotations

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.contracts.common import utc_instant

from .contracts import (
    AutonomyTrigger,
    AutonomyTriggerKind,
    CommitmentState,
    CommitmentStatus,
    DueCommitmentOrder,
    GoalCommitmentSnapshot,
    GoalContextBuildError,
    GoalContextFailureCode,
    GoalContextItemKind,
    GoalContextView,
    GoalState,
    GoalStatus,
)


def build_goal_context_view(
    snapshot: GoalCommitmentSnapshot,
    *,
    bounds_policy: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    due_order: DueCommitmentOrder | None = None,
) -> GoalContextView:
    if not isinstance(snapshot, GoalCommitmentSnapshot):
        raise ValueError("snapshotはGoalCommitmentSnapshotでなければなりません")
    if not isinstance(bounds_policy, BrainOperationalBoundsPolicy):
        raise ValueError("bounds_policyはBrainOperationalBoundsPolicyでなければなりません")
    if due_order is not None and not isinstance(due_order, DueCommitmentOrder):
        raise ValueError("due_orderはDueCommitmentOrderでなければなりません")
    if due_order is not None and due_order.goal_revision != snapshot.revision:
        raise ValueError("due順序のgoal revisionが古くなっています")
    _validate_reference_bounds(snapshot, bounds_policy)
    bounds = bounds_policy.goal_context
    active = sorted(
        (item for item in snapshot.goals if item.status is GoalStatus.ACTIVE),
        key=lambda item: (-item.priority, -utc_instant(item.updated_at).timestamp(), item.goal_id),
    )[: bounds.max_active_goals]
    suspended = sorted(
        (item for item in snapshot.goals if item.status is GoalStatus.SUSPENDED),
        key=lambda item: (-item.priority, -utc_instant(item.updated_at).timestamp(), item.goal_id),
    )[: bounds.max_suspended_goals]
    commitment_by_id = {item.commitment_id: item for item in snapshot.commitments}
    due_ids = () if due_order is None else due_order.commitment_ids
    if set(due_ids) - set(commitment_by_id):
        raise ValueError("due順序が存在しないCommitmentを参照しています")
    due = tuple(commitment_by_id[item_id] for item_id in due_ids)
    if any(item.terminal for item in due):
        raise ValueError("due順序がterminal Commitmentを参照しています")
    active_commitments = tuple(
        item
        for item in snapshot.commitments
        if item.status is CommitmentStatus.ACTIVE and item.commitment_id not in set(due_ids)
    )
    commitments = (
        due
        + tuple(
            sorted(
                active_commitments,
                key=lambda item: (
                    -item.priority,
                    -utc_instant(item.updated_at).timestamp(),
                    item.commitment_id,
                ),
            )
        )
    )[: bounds.max_due_or_active_commitments]
    recent = sorted(
        [
            (item.updated_at, GoalContextItemKind.GOAL.value, item.goal_id, item)
            for item in snapshot.goals
        ]
        + [
            (item.updated_at, GoalContextItemKind.COMMITMENT.value, item.commitment_id, item)
            for item in snapshot.commitments
        ],
        key=lambda item: (-utc_instant(item[0]).timestamp(), item[1], item[2]),
    )[: bounds.max_recently_changed_items]
    recent_goals = tuple(item for _, _, _, item in recent if isinstance(item, GoalState))
    recent_commitments = tuple(
        item for _, _, _, item in recent if isinstance(item, CommitmentState)
    )
    return GoalContextView(
        snapshot.revision,
        bounds_policy.policy_id,
        bounds_policy.policy_revision,
        tuple(active),
        tuple(suspended),
        tuple(commitments),
        tuple(recent_goals),
        tuple(recent_commitments),
    )


def _validate_reference_bounds(
    snapshot: GoalCommitmentSnapshot, bounds_policy: BrainOperationalBoundsPolicy
) -> None:
    bounds = bounds_policy.goal_context
    for item in snapshot.goals:
        if (
            sum(
                len(values)
                for values in (
                    item.motivation_refs,
                    item.commitment_refs,
                    item.precondition_ids,
                    item.completion_condition_refs,
                )
            )
            > bounds.max_refs_per_goal
        ):
            raise GoalContextBuildError(GoalContextFailureCode.ITEM_TOO_LARGE)
    for commitment in snapshot.commitments:
        if (
            sum(
                len(values)
                for values in (
                    commitment.source_event_ids,
                    commitment.related_goal_refs,
                    commitment.due_condition_refs,
                    commitment.release_condition_refs,
                )
            )
            > bounds.max_refs_per_commitment
        ):
            raise GoalContextBuildError(GoalContextFailureCode.ITEM_TOO_LARGE)


def autonomy_triggers(snapshot: GoalCommitmentSnapshot) -> tuple[AutonomyTrigger, ...]:
    triggers: list[AutonomyTrigger] = []
    for goal in snapshot.goals:
        kind = {
            GoalStatus.PROPOSED: AutonomyTriggerKind.PENDING_GOAL,
            GoalStatus.ACTIVE: AutonomyTriggerKind.ACTIVE_GOAL,
            GoalStatus.SUSPENDED: AutonomyTriggerKind.SUSPENDED_GOAL,
        }.get(goal.status)
        if kind is not None:
            triggers.append(
                AutonomyTrigger(
                    f"goal-trigger:{goal.goal_id}:{snapshot.revision}",
                    kind,
                    goal.goal_id,
                    snapshot.revision,
                    goal.priority,
                )
            )
    for commitment in snapshot.commitments:
        if commitment.status in {
            CommitmentStatus.PROPOSED,
            CommitmentStatus.ACTIVE,
            CommitmentStatus.SUSPENDED,
        }:
            kind = (
                AutonomyTriggerKind.COMMITMENT_DUE_CHECK
                if commitment.due_condition_refs
                else AutonomyTriggerKind.COMMITMENT_REVIEW
            )
            triggers.append(
                AutonomyTrigger(
                    f"commitment-trigger:{commitment.commitment_id}:{snapshot.revision}",
                    kind,
                    commitment.commitment_id,
                    snapshot.revision,
                    commitment.priority,
                )
            )
    return tuple(sorted(triggers, key=lambda item: (-item.priority, item.trigger_id)))
