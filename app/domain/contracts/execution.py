from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from datetime import datetime
from enum import Enum
from typing import cast

from .common import (
    JsonValue,
    RevisionVector,
    freeze_json,
    require_aware,
    require_identifier,
    thaw_json,
    timestamp_to_json,
    utc_instant,
)


class ExecutionStatus(str, Enum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    PLANNED = "planned"
    STARTED = "started"
    OBSERVABLE = "observable"
    APPLIED = "applied"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SUPERSEDED = "superseded"


_ALLOWED_TRANSITIONS: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.REQUESTED: frozenset(
        {
            ExecutionStatus.ACCEPTED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.UNSUPPORTED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }
    ),
    ExecutionStatus.ACCEPTED: frozenset(
        {
            ExecutionStatus.PLANNED,
            ExecutionStatus.STARTED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.UNSUPPORTED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }
    ),
    ExecutionStatus.PLANNED: frozenset(
        {
            ExecutionStatus.STARTED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }
    ),
    ExecutionStatus.STARTED: frozenset(
        {
            ExecutionStatus.OBSERVABLE,
            ExecutionStatus.APPLIED,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }
    ),
    ExecutionStatus.OBSERVABLE: frozenset(
        {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }
    ),
    ExecutionStatus.APPLIED: frozenset(
        {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }
    ),
}

_EFFECT_STATUSES = frozenset(
    {ExecutionStatus.OBSERVABLE, ExecutionStatus.APPLIED, ExecutionStatus.COMPLETED}
)
_TRANSITION_PROOF = object()
_UNSET = object()


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    command_id: str
    status: ExecutionStatus
    occurred_at: datetime
    revisions: RevisionVector
    details: JsonValue = field(default_factory=dict)
    effect_refs: tuple[str, ...] = ()
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        require_identifier(self.command_id, "command_id")
        require_aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "details", freeze_json(self.details))
        effect_refs = tuple(self.effect_refs)
        if any(not isinstance(item, str) or not item.strip() for item in effect_refs):
            raise ValueError("effect_refs must contain non-empty strings")
        if len(set(effect_refs)) != len(effect_refs):
            raise ValueError("effect_refs must be unique")
        object.__setattr__(self, "effect_refs", effect_refs)
        if self.status is ExecutionStatus.REQUESTED:
            if _proof is not None:
                raise ValueError("requested snapshot cannot use transition proof")
            if effect_refs:
                raise ValueError("requested snapshot cannot contain effect_refs")
        elif _proof is not _TRANSITION_PROOF:
            raise ValueError("non-requested snapshots require a validated transition")

    def transition_to(
        self,
        status: ExecutionStatus,
        occurred_at: datetime,
        *,
        details: JsonValue | object = _UNSET,
        effect_refs: tuple[str, ...] | list[str] | None = None,
    ) -> ExecutionResult:
        if status not in _ALLOWED_TRANSITIONS.get(self.status, frozenset()):
            raise ValueError(f"invalid execution transition: {self.status.value} -> {status.value}")
        require_aware(occurred_at, "occurred_at")
        if utc_instant(occurred_at) < utc_instant(self.occurred_at):
            raise ValueError("execution timestamp cannot move backwards")

        supplied_refs = () if effect_refs is None else tuple(effect_refs)
        new_refs = tuple(item for item in supplied_refs if item not in self.effect_refs)
        if new_refs and status not in _EFFECT_STATUSES:
            raise ValueError(f"{status.value} cannot introduce effect_refs")
        merged_refs = self.effect_refs + new_refs
        next_details = self.details if details is _UNSET else cast(JsonValue, details)
        return ExecutionResult(
            command_id=self.command_id,
            status=status,
            occurred_at=occurred_at,
            revisions=self.revisions,
            details=next_details,
            effect_refs=merged_refs,
            _proof=_TRANSITION_PROOF,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "status": self.status.value,
            "occurred_at": timestamp_to_json(self.occurred_at),
            "revisions": self.revisions.to_dict(),
            "details": thaw_json(self.details),
            "effect_refs": list(self.effect_refs),
        }


class AsyncWorkStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AsyncWorkResult:
    request_id: str
    status: AsyncWorkStatus
    revisions: RevisionVector
    completed_at: datetime
    result: JsonValue
    started_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.request_id, "request_id")
        require_aware(self.completed_at, "completed_at")
        if self.started_at is not None:
            require_aware(self.started_at, "started_at")
            if utc_instant(self.started_at) > utc_instant(self.completed_at):
                raise ValueError("started_at cannot be later than completed_at")
        if self.status is AsyncWorkStatus.SUCCEEDED and self.started_at is None:
            raise ValueError("succeeded work requires started_at")
        if self.error_code is not None:
            require_identifier(self.error_code, "error_code")
        object.__setattr__(self, "result", freeze_json(self.result))

    @property
    def is_committable(self) -> bool:
        return self.status is AsyncWorkStatus.SUCCEEDED

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "revisions": self.revisions.to_dict(),
            "started_at": None
            if self.started_at is None
            else timestamp_to_json(self.started_at),
            "completed_at": timestamp_to_json(self.completed_at),
            "result": thaw_json(self.result),
            "error_code": self.error_code,
        }
