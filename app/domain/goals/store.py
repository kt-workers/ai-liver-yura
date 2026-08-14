from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import Lock

from app.domain.contracts.common import utc_instant
from app.domain.executive import (
    CommitmentTransitionOperation,
    CommittedExecutiveDecision,
    GoalTransitionOperation,
)

from .contracts import (
    CommitmentState,
    CommitmentStatus,
    GoalCommitmentSnapshot,
    GoalKind,
    GoalState,
    GoalStatus,
    InterruptionPolicy,
)

_GOAL_STATUS_BY_OPERATION = {
    GoalTransitionOperation.ACTIVATE: GoalStatus.ACTIVE,
    GoalTransitionOperation.SUSPEND: GoalStatus.SUSPENDED,
    GoalTransitionOperation.RESUME: GoalStatus.ACTIVE,
    GoalTransitionOperation.COMPLETE: GoalStatus.COMPLETED,
    GoalTransitionOperation.FAIL: GoalStatus.FAILED,
    GoalTransitionOperation.ABANDON: GoalStatus.ABANDONED,
    GoalTransitionOperation.SUPERSEDE: GoalStatus.SUPERSEDED,
}

_GOAL_SOURCES = {
    GoalTransitionOperation.ACTIVATE: {GoalStatus.PROPOSED},
    GoalTransitionOperation.SUSPEND: {GoalStatus.ACTIVE},
    GoalTransitionOperation.RESUME: {GoalStatus.SUSPENDED},
    GoalTransitionOperation.COMPLETE: {GoalStatus.ACTIVE},
    GoalTransitionOperation.FAIL: {GoalStatus.ACTIVE},
    GoalTransitionOperation.ABANDON: {
        GoalStatus.PROPOSED,
        GoalStatus.ACTIVE,
        GoalStatus.SUSPENDED,
    },
    GoalTransitionOperation.SUPERSEDE: {
        GoalStatus.PROPOSED,
        GoalStatus.ACTIVE,
        GoalStatus.SUSPENDED,
    },
}

_COMMITMENT_STATUS_BY_OPERATION = {
    CommitmentTransitionOperation.ACTIVATE: CommitmentStatus.ACTIVE,
    CommitmentTransitionOperation.SUSPEND: CommitmentStatus.SUSPENDED,
    CommitmentTransitionOperation.RESUME: CommitmentStatus.ACTIVE,
    CommitmentTransitionOperation.RELEASE: CommitmentStatus.RELEASED,
    CommitmentTransitionOperation.FULFILL: CommitmentStatus.FULFILLED,
    CommitmentTransitionOperation.VIOLATE: CommitmentStatus.VIOLATED,
}

_COMMITMENT_SOURCES = {
    CommitmentTransitionOperation.ACTIVATE: {CommitmentStatus.PROPOSED},
    CommitmentTransitionOperation.SUSPEND: {CommitmentStatus.ACTIVE},
    CommitmentTransitionOperation.RESUME: {CommitmentStatus.SUSPENDED},
    CommitmentTransitionOperation.RELEASE: {
        CommitmentStatus.PROPOSED,
        CommitmentStatus.ACTIVE,
        CommitmentStatus.SUSPENDED,
    },
    CommitmentTransitionOperation.FULFILL: {CommitmentStatus.ACTIVE},
    CommitmentTransitionOperation.VIOLATE: {
        CommitmentStatus.ACTIVE,
        CommitmentStatus.SUSPENDED,
    },
}


class GoalCommitmentStore:
    """current Goal/Commitmentの単一同期State Authority。"""

    def __init__(self, initial: GoalCommitmentSnapshot | None = None) -> None:
        if initial is not None and not isinstance(initial, GoalCommitmentSnapshot):
            raise ValueError("initial must be GoalCommitmentSnapshot")
        initial_time = datetime.min.replace(tzinfo=timezone.utc)
        self._snapshot = initial or GoalCommitmentSnapshot(0, (), (), initial_time)
        self._validate_references(
            {item.goal_id: item for item in self._snapshot.goals},
            {item.commitment_id: item for item in self._snapshot.commitments},
        )
        self._decision_ids: set[str] = set()
        self._intent_ids: set[str] = set()
        self._lock = Lock()

    def snapshot(self) -> GoalCommitmentSnapshot:
        with self._lock:
            return self._snapshot

    def apply(self, decision: CommittedExecutiveDecision) -> GoalCommitmentSnapshot:
        if not isinstance(decision, CommittedExecutiveDecision):
            raise ValueError("decision must be CommittedExecutiveDecision")
        candidate = decision.candidate
        transitions = candidate.goal_transition_intents + candidate.commitment_transition_intents
        if not transitions:
            raise ValueError("decision does not contain state transitions")
        with self._lock:
            if decision.decision_id in self._decision_ids:
                raise ValueError("decision is already applied")
            intent_ids = {item.intent_id for item in transitions}
            if intent_ids.intersection(self._intent_ids):
                raise ValueError("transition intent is already applied")
            current = self._snapshot
            if candidate.goal_revision != current.revision:
                raise ValueError("executive candidate goal revision is stale")
            if utc_instant(decision.committed_at) < utc_instant(current.updated_at):
                raise ValueError("decision time predates current state")
            if any(item.expected_goal_revision != current.revision for item in transitions):
                raise ValueError("goal transition batch is stale")
            next_revision = current.revision + 1
            goals = {item.goal_id: item for item in current.goals}
            commitments = {item.commitment_id: item for item in current.commitments}
            for transition in candidate.goal_transition_intents:
                self._apply_goal(
                    goals,
                    transition,
                    decision.decision_id,
                    decision.committed_at,
                    next_revision,
                )
            for commitment_transition in candidate.commitment_transition_intents:
                self._apply_commitment(
                    goals,
                    commitments,
                    commitment_transition,
                    candidate.source_event_ids,
                    decision.decision_id,
                    decision.committed_at,
                    next_revision,
                )
            self._validate_references(goals, commitments)
            snapshot = GoalCommitmentSnapshot(
                next_revision,
                tuple(sorted(goals.values(), key=lambda item: item.goal_id)),
                tuple(sorted(commitments.values(), key=lambda item: item.commitment_id)),
                decision.committed_at,
            )
            self._snapshot = snapshot
            self._decision_ids.add(decision.decision_id)
            self._intent_ids.update(intent_ids)
            return snapshot

    @staticmethod
    def _validate_references(
        goals: dict[str, GoalState], commitments: dict[str, CommitmentState]
    ) -> None:
        commitment_ids = set(commitments)
        if any(set(goal.commitment_refs) - commitment_ids for goal in goals.values()):
            raise ValueError("goal commitment reference does not exist")
        goal_ids = set(goals)
        if any(set(item.related_goal_refs) - goal_ids for item in commitments.values()):
            raise ValueError("commitment goal reference does not exist")

    @staticmethod
    def _apply_goal(
        goals: dict[str, GoalState],
        transition: object,
        decision_id: str,
        occurred_at: datetime,
        revision: int,
    ) -> None:
        from app.domain.executive import GoalTransitionIntent

        assert isinstance(transition, GoalTransitionIntent)
        operation = transition.operation
        if operation is GoalTransitionOperation.CREATE:
            goal_id = transition.goal_spec_ref
            assert goal_id is not None
            if goal_id in goals:
                raise ValueError("goal already exists")
            payload = transition.payload
            assert payload.semantic_goal_ref is not None and payload.priority is not None
            assert payload.goal_kind is not None and payload.interruption_policy is not None
            goals[goal_id] = GoalState(
                goal_id,
                GoalKind(payload.goal_kind),
                payload.semantic_goal_ref,
                payload.target_ref,
                decision_id,
                GoalStatus.PROPOSED,
                payload.priority,
                transition.reason_refs,
                payload.commitment_refs,
                payload.precondition_ids,
                payload.completion_condition_refs,
                InterruptionPolicy(payload.interruption_policy),
                occurred_at,
                occurred_at,
                revision,
            )
            return
        goal_id = transition.goal_ref
        assert goal_id is not None
        goal = goals.get(goal_id)
        if goal is None:
            raise ValueError("goal does not exist")
        if operation is GoalTransitionOperation.REPRIORITIZE:
            if goal.terminal:
                raise ValueError("terminal goal cannot be reprioritized")
            assert transition.payload.priority is not None
            goals[goal_id] = replace(
                goal,
                priority=transition.payload.priority,
                updated_at=occurred_at,
                revision=revision,
            )
            return
        if goal.status not in _GOAL_SOURCES[operation]:
            raise ValueError("illegal goal lifecycle transition")
        if operation is GoalTransitionOperation.SUPERSEDE:
            superseding = transition.payload.superseding_goal_ref
            if superseding is None or superseding == goal_id or superseding not in goals:
                raise ValueError("superseding goal must exist and differ")
        goals[goal_id] = replace(
            goal,
            status=_GOAL_STATUS_BY_OPERATION[operation],
            updated_at=occurred_at,
            revision=revision,
        )

    @staticmethod
    def _apply_commitment(
        goals: dict[str, GoalState],
        commitments: dict[str, CommitmentState],
        transition: object,
        source_event_ids: tuple[str, ...],
        decision_id: str,
        occurred_at: datetime,
        revision: int,
    ) -> None:
        from app.domain.executive import CommitmentTransitionIntent

        assert isinstance(transition, CommitmentTransitionIntent)
        operation = transition.operation
        if operation is CommitmentTransitionOperation.CREATE:
            commitment_id = transition.commitment_spec_ref
            assert commitment_id is not None
            if commitment_id in commitments:
                raise ValueError("commitment already exists")
            semantic_ref = transition.payload.semantic_commitment_ref
            strength, priority = transition.payload.strength, transition.payload.priority
            assert semantic_ref is not None and strength is not None and priority is not None
            if set(transition.payload.related_goal_refs) - set(goals):
                raise ValueError("related commitment goal does not exist")
            duplicate_identity = (
                semantic_ref,
                transition.payload.counterparty_ref,
                transition.payload.related_goal_refs,
                transition.payload.due_condition_refs,
                transition.payload.release_condition_refs,
            )
            if any(
                not item.terminal
                and (
                    item.semantic_commitment_ref,
                    item.counterparty_ref,
                    item.related_goal_refs,
                    item.due_condition_refs,
                    item.release_condition_refs,
                )
                == duplicate_identity
                for item in commitments.values()
            ):
                raise ValueError("duplicate active commitment specification")
            commitments[commitment_id] = CommitmentState(
                commitment_id,
                semantic_ref,
                transition.payload.counterparty_ref,
                source_event_ids,
                decision_id,
                transition.payload.related_goal_refs,
                CommitmentStatus.PROPOSED,
                strength,
                priority,
                transition.payload.due_condition_refs,
                transition.payload.release_condition_refs,
                occurred_at,
                occurred_at,
                revision,
            )
            return
        commitment_id = transition.commitment_ref
        assert commitment_id is not None
        commitment = commitments.get(commitment_id)
        if commitment is None:
            raise ValueError("commitment does not exist")
        if commitment.status not in _COMMITMENT_SOURCES[operation]:
            raise ValueError("illegal commitment lifecycle transition")
        commitments[commitment_id] = replace(
            commitment,
            status=_COMMITMENT_STATUS_BY_OPERATION[operation],
            updated_at=occurred_at,
            revision=revision,
        )
