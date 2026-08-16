from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.contracts import SourceLifecycleOperation
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    timestamp_to_json,
    utc_instant,
)


class GoalKind(str, Enum):
    GENERAL = "general"
    ACTIVITY = "activity"
    SOCIAL = "social"
    EXPLORATION = "exploration"
    MAINTENANCE = "maintenance"


class GoalStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class CommitmentStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RELEASED = "released"
    FULFILLED = "fulfilled"
    VIOLATED = "violated"


class InterruptionPolicy(str, Enum):
    INTERRUPTIBLE = "interruptible"
    RESUMABLE = "resumable"
    PROTECTED = "protected"


class AutonomyTriggerKind(str, Enum):
    PENDING_GOAL = "pending_goal"
    ACTIVE_GOAL = "active_goal"
    SUSPENDED_GOAL = "suspended_goal"
    COMMITMENT_REVIEW = "commitment_review"
    COMMITMENT_DUE_CHECK = "commitment_due_check"


def _ids(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    result = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    return result


def _score(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError(f"{name} must be an int between 0 and 100")


@dataclass(frozen=True, slots=True)
class GoalState:
    goal_id: str
    kind: GoalKind
    semantic_goal_ref: str
    target_ref: str | None
    created_from_decision_id: str
    status: GoalStatus
    priority: int
    motivation_refs: tuple[str, ...]
    commitment_refs: tuple[str, ...]
    precondition_ids: tuple[str, ...]
    completion_condition_refs: tuple[str, ...]
    interruption_policy: InterruptionPolicy
    created_at: datetime
    updated_at: datetime
    revision: int

    def __post_init__(self) -> None:
        for name in ("goal_id", "semantic_goal_ref", "created_from_decision_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.kind, GoalKind) or not isinstance(self.status, GoalStatus):
            raise ValueError("goal kind and status must be typed enums")
        if not isinstance(self.interruption_policy, InterruptionPolicy):
            raise ValueError("interruption_policy must be InterruptionPolicy")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        _score(self.priority, "priority")
        for name in (
            "motivation_refs",
            "commitment_refs",
            "precondition_ids",
            "completion_condition_refs",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if utc_instant(self.updated_at) < utc_instant(self.created_at):
            raise ValueError("goal updated_at cannot predate created_at")
        require_revision(self.revision, "revision")

    @property
    def terminal(self) -> bool:
        return self.status in {
            GoalStatus.COMPLETED,
            GoalStatus.ABANDONED,
            GoalStatus.FAILED,
            GoalStatus.SUPERSEDED,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "kind": self.kind.value,
            "semantic_goal_ref": self.semantic_goal_ref,
            "target_ref": self.target_ref,
            "created_from_decision_id": self.created_from_decision_id,
            "status": self.status.value,
            "priority": self.priority,
            "motivation_refs": list(self.motivation_refs),
            "commitment_refs": list(self.commitment_refs),
            "precondition_ids": list(self.precondition_ids),
            "completion_condition_refs": list(self.completion_condition_refs),
            "interruption_policy": self.interruption_policy.value,
            "created_at": timestamp_to_json(self.created_at),
            "updated_at": timestamp_to_json(self.updated_at),
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class CommitmentState:
    commitment_id: str
    semantic_commitment_ref: str
    counterparty_ref: str | None
    source_event_ids: tuple[str, ...]
    source_decision_id: str
    related_goal_refs: tuple[str, ...]
    status: CommitmentStatus
    strength: int
    priority: int
    due_condition_refs: tuple[str, ...]
    release_condition_refs: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    revision: int

    def __post_init__(self) -> None:
        for name in ("commitment_id", "semantic_commitment_ref", "source_decision_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.status, CommitmentStatus):
            raise ValueError("status must be CommitmentStatus")
        if self.counterparty_ref is not None:
            require_identifier(self.counterparty_ref, "counterparty_ref")
        for name in (
            "source_event_ids",
            "related_goal_refs",
            "due_condition_refs",
            "release_condition_refs",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        if not self.source_event_ids:
            raise ValueError("source_event_ids must not be empty")
        _score(self.strength, "strength")
        _score(self.priority, "priority")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if utc_instant(self.updated_at) < utc_instant(self.created_at):
            raise ValueError("commitment updated_at cannot predate created_at")
        require_revision(self.revision, "revision")

    @property
    def terminal(self) -> bool:
        return self.status in {
            CommitmentStatus.RELEASED,
            CommitmentStatus.FULFILLED,
            CommitmentStatus.VIOLATED,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "commitment_id": self.commitment_id,
            "semantic_commitment_ref": self.semantic_commitment_ref,
            "counterparty_ref": self.counterparty_ref,
            "source_event_ids": list(self.source_event_ids),
            "source_decision_id": self.source_decision_id,
            "related_goal_refs": list(self.related_goal_refs),
            "status": self.status.value,
            "strength": self.strength,
            "priority": self.priority,
            "due_condition_refs": list(self.due_condition_refs),
            "release_condition_refs": list(self.release_condition_refs),
            "created_at": timestamp_to_json(self.created_at),
            "updated_at": timestamp_to_json(self.updated_at),
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class GoalCommitmentSnapshot:
    revision: int
    goals: tuple[GoalState, ...]
    commitments: tuple[CommitmentState, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        require_revision(self.revision, "revision")
        require_aware(self.updated_at, "updated_at")
        for name, expected in (("goals", GoalState), ("commitments", CommitmentState)):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)) or any(
                not isinstance(item, expected) for item in values
            ):
                raise ValueError(f"{name} contains an invalid value")
            values = tuple(values)
            identifiers = [
                getattr(item, "goal_id", getattr(item, "commitment_id", None)) for item in values
            ]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} ids must be unique")
            if any(item.revision > self.revision for item in values):
                raise ValueError(f"{name} state cannot be newer than snapshot")
            if any(utc_instant(item.updated_at) > utc_instant(self.updated_at) for item in values):
                raise ValueError(f"{name} state cannot be newer than snapshot time")
            object.__setattr__(self, name, values)

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "goals": [item.to_dict() for item in self.goals],
            "commitments": [item.to_dict() for item in self.commitments],
            "updated_at": timestamp_to_json(self.updated_at),
        }


@dataclass(frozen=True, slots=True)
class GoalContextView:
    goal_revision: int
    active_goals: tuple[GoalState, ...]
    suspended_goals: tuple[GoalState, ...]
    commitments: tuple[CommitmentState, ...]
    recently_changed_goals: tuple[GoalState, ...]
    recently_changed_commitments: tuple[CommitmentState, ...]

    def __post_init__(self) -> None:
        require_revision(self.goal_revision, "goal_revision")
        for name, expected in (
            ("active_goals", GoalState),
            ("suspended_goals", GoalState),
            ("commitments", CommitmentState),
            ("recently_changed_goals", GoalState),
            ("recently_changed_commitments", CommitmentState),
        ):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)) or any(
                not isinstance(item, expected) for item in values
            ):
                raise ValueError(f"{name} contains an invalid value")
            object.__setattr__(self, name, tuple(values))

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_revision": self.goal_revision,
            "active_goals": [item.to_dict() for item in self.active_goals],
            "suspended_goals": [item.to_dict() for item in self.suspended_goals],
            "commitments": [item.to_dict() for item in self.commitments],
            "recently_changed_goals": [item.to_dict() for item in self.recently_changed_goals],
            "recently_changed_commitments": [
                item.to_dict() for item in self.recently_changed_commitments
            ],
        }


@dataclass(frozen=True, slots=True)
class AutonomyTrigger:
    trigger_id: str
    kind: AutonomyTriggerKind
    source_ref: str
    goal_revision: int
    priority: int

    def __post_init__(self) -> None:
        require_identifier(self.trigger_id, "trigger_id")
        require_identifier(self.source_ref, "source_ref")
        if not isinstance(self.kind, AutonomyTriggerKind):
            raise ValueError("kind must be AutonomyTriggerKind")
        require_revision(self.goal_revision, "goal_revision")
        _score(self.priority, "priority")

    def to_dict(self) -> dict[str, object]:
        return {
            "trigger_id": self.trigger_id,
            "kind": self.kind.value,
            "source_ref": self.source_ref,
            "goal_revision": self.goal_revision,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class GoalLifecycleProjectionFact:
    fact_id: str
    goal_id: str
    operation: SourceLifecycleOperation
    source_revision: int
    expected_source_revision: int | None
    status: GoalStatus
    priority: int
    goal_store_revision: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        for name in ("fact_id", "goal_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.operation, SourceLifecycleOperation) or not isinstance(
            self.status, GoalStatus
        ):
            raise ValueError("goal lifecycle factが不正です")
        require_revision(self.source_revision, "source_revision")
        require_revision(self.expected_source_revision, "expected_source_revision", optional=True)
        if (self.operation is SourceLifecycleOperation.OPEN) != (
            self.expected_source_revision is None
        ):
            raise ValueError("goal lifecycle operationとexpected revisionが一致しません")
        _score(self.priority, "priority")
        require_revision(self.goal_store_revision, "goal_store_revision")
        require_aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class CommitmentLifecycleProjectionFact:
    fact_id: str
    commitment_id: str
    operation: SourceLifecycleOperation
    source_revision: int
    expected_source_revision: int | None
    status: CommitmentStatus
    priority: int
    goal_store_revision: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        for name in ("fact_id", "commitment_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.operation, SourceLifecycleOperation) or not isinstance(
            self.status, CommitmentStatus
        ):
            raise ValueError("commitment lifecycle factが不正です")
        require_revision(self.source_revision, "source_revision")
        require_revision(self.expected_source_revision, "expected_source_revision", optional=True)
        if (self.operation is SourceLifecycleOperation.OPEN) != (
            self.expected_source_revision is None
        ):
            raise ValueError("commitment lifecycle operationとexpected revisionが一致しません")
        _score(self.priority, "priority")
        require_revision(self.goal_store_revision, "goal_store_revision")
        require_aware(self.occurred_at, "occurred_at")
