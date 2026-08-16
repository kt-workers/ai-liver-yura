from __future__ import annotations

from .contracts import (
    AutonomyTrigger,
    AutonomyTriggerKind,
    CommitmentStatus,
    GoalCommitmentSnapshot,
    GoalContextView,
    GoalStatus,
)


def build_goal_context_view(
    snapshot: GoalCommitmentSnapshot,
    *,
    max_active: int = 8,
    max_suspended: int = 4,
    max_commitments: int = 8,
    max_recent: int = 8,
) -> GoalContextView:
    for name, value in (
        ("max_active", max_active),
        ("max_suspended", max_suspended),
        ("max_commitments", max_commitments),
        ("max_recent", max_recent),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive int")
    active = sorted(
        (item for item in snapshot.goals if item.status is GoalStatus.ACTIVE),
        key=lambda item: (-item.priority, item.goal_id),
    )[:max_active]
    suspended = sorted(
        (item for item in snapshot.goals if item.status is GoalStatus.SUSPENDED),
        key=lambda item: (-item.priority, item.goal_id),
    )[:max_suspended]
    commitments = sorted(
        (item for item in snapshot.commitments if not item.terminal),
        key=lambda item: (-item.priority, item.commitment_id),
    )[:max_commitments]
    recent_goals = sorted(
        snapshot.goals,
        key=lambda item: (-item.revision, item.goal_id),
    )[:max_recent]
    recent_commitments = sorted(
        snapshot.commitments,
        key=lambda item: (-item.revision, item.commitment_id),
    )[:max_recent]
    return GoalContextView(
        snapshot.revision,
        tuple(active),
        tuple(suspended),
        tuple(commitments),
        tuple(recent_goals),
        tuple(recent_commitments),
    )


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
