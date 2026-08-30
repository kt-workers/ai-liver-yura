from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from math import isfinite
from typing import Generic, TypeVar

from app.domain.contracts import RevisionVector
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    utc_instant,
)

T = TypeVar("T")


class WorkPriority(IntEnum):
    CRITICAL = 0
    FOREGROUND = 1
    NORMAL = 2
    BACKGROUND = 3


class QueuePolicy(str, Enum):
    REJECT_NEW = "reject_new"
    DROP_OLDEST = "drop_oldest"
    LATEST_WINS = "latest_wins"
    COALESCE = "coalesce"
    REPLACE_SAME_KEY = "replace_same_key"


class QueueAdmissionStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REPLACED = "replaced"
    COALESCED = "coalesced"
    DROPPED_OLDEST = "dropped_oldest"


class WorkDisposition(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class CoordinatorState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class RuntimeHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"


class LaneErrorPolicy(str, Enum):
    ISOLATE = "isolate"
    FAIL_FAST_CONTROLLED = "fail_fast_controlled"
    FAIL_FAST = "fail_fast_controlled"


def _require_positive_int(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive int")


def _require_non_negative_finite(value: float, name: str) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class RuntimeSchedulerPolicy:
    policy_id: str
    policy_revision: int
    max_priority_burst: int

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        _require_positive_int(self.max_priority_burst, "max_priority_burst")


@dataclass(frozen=True, slots=True)
class RuntimeLanePolicy:
    lane_id: str
    queue_capacity: int
    queue_policy: QueuePolicy
    max_in_flight: int
    cancellation_grace_seconds: float
    error_isolation: LaneErrorPolicy

    def __post_init__(self) -> None:
        require_identifier(self.lane_id, "lane_id")
        _require_positive_int(self.queue_capacity, "queue_capacity")
        _require_positive_int(self.max_in_flight, "max_in_flight")
        _require_non_negative_finite(
            self.cancellation_grace_seconds,
            "cancellation_grace_seconds",
        )


@dataclass(frozen=True, slots=True)
class RuntimeWorkItem(Generic[T]):
    work_id: str
    lane_id: str
    payload: T
    priority: WorkPriority
    revisions: RevisionVector
    created_at: datetime
    queue_key: str | None = None
    deadline_at: datetime | None = None
    interruptible: bool = True
    shutdown_control: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.work_id, "work_id")
        require_identifier(self.lane_id, "lane_id")
        if self.queue_key is not None:
            require_identifier(self.queue_key, "queue_key")
        require_aware(self.created_at, "created_at")
        if self.deadline_at is not None:
            require_aware(self.deadline_at, "deadline_at")
            if utc_instant(self.deadline_at) <= utc_instant(self.created_at):
                raise ValueError("deadline_at must be later than created_at")
        if type(self.shutdown_control) is not bool:
            raise ValueError("shutdown_control must be a bool")
        if self.shutdown_control and self.priority is not WorkPriority.CRITICAL:
            raise ValueError("shutdown_control requires critical priority")


@dataclass(frozen=True, slots=True)
class QueueAdmission:
    status: QueueAdmissionStatus
    admitted_work_id: str | None
    displaced_work_ids: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.status is not QueueAdmissionStatus.REJECTED


@dataclass(frozen=True, slots=True)
class CancellationRecord:
    work_id: str
    reason: str
    requested_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.work_id, "work_id")
        require_identifier(self.reason, "reason")
        require_aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class WorkOutcome(Generic[T]):
    work_id: str
    lane_id: str
    disposition: WorkDisposition
    completed_at: datetime
    result: T | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.work_id, "work_id")
        require_identifier(self.lane_id, "lane_id")
        require_aware(self.completed_at, "completed_at")
        if self.error is not None:
            require_identifier(self.error, "error")


@dataclass(frozen=True, slots=True)
class LaneDiagnostics:
    lane_id: str
    queue_depth: int
    in_flight: int
    completed: int
    failed: int
    cancelled: int
    stale: int
    rejected: int
    queued_by_priority: tuple[tuple[WorkPriority, int], ...]
    oldest_queued_age_seconds: float | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class RuntimeDiagnosticsSnapshot:
    state: CoordinatorState
    health: RuntimeHealth
    owned_task_count: int
    lanes: tuple[LaneDiagnostics, ...]
    captured_at: datetime
