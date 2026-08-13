from __future__ import annotations

from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import cast

from .common import (
    JsonInput,
    JsonValue,
    RevisionVector,
    freeze_json,
    jsonable,
    require_aware_datetime,
    require_non_empty,
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

    @property
    def is_terminal(self) -> bool:
        return self in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.UNSUPPORTED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }


_ALLOWED_TRANSITIONS: Mapping[ExecutionStatus, frozenset[ExecutionStatus]] = {
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

_EXECUTION_TRANSITION_PROOF = object()


def validate_execution_transition(
    current: ExecutionStatus,
    target: ExecutionStatus,
) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"invalid execution transition: {current.value} -> {target.value}")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_id: str
    command_id: str
    status: ExecutionStatus
    occurred_at: datetime
    revisions: RevisionVector
    details: Mapping[str, JsonInput] = field(default_factory=dict)
    effect_refs: tuple[str, ...] = ()
    reason_code: str | None = None
    _transition_proof: InitVar[object | None] = None

    def __post_init__(self, _transition_proof: object | None) -> None:
        require_non_empty("execution_id", self.execution_id)
        require_non_empty("command_id", self.command_id)
        require_aware_datetime("occurred_at", self.occurred_at)
        if (
            self.status is not ExecutionStatus.REQUESTED
            and _transition_proof is not _EXECUTION_TRANSITION_PROOF
        ):
            raise ValueError(
                "non-requested ExecutionResult snapshots require a validated transition"
            )
        if self.reason_code is not None:
            require_non_empty("reason_code", self.reason_code)
        if len(set(self.effect_refs)) != len(self.effect_refs):
            raise ValueError("effect_refs must not contain duplicates")
        for effect_ref in self.effect_refs:
            require_non_empty("effect_ref", effect_ref)
        frozen = {key: freeze_json(value) for key, value in self.details.items()}
        object.__setattr__(
            self,
            "details",
            cast(Mapping[str, JsonValue], MappingProxyType(frozen)),
        )

    @classmethod
    def requested(
        cls,
        *,
        execution_id: str,
        command_id: str,
        occurred_at: datetime,
        revisions: RevisionVector,
    ) -> ExecutionResult:
        return cls(
            execution_id=execution_id,
            command_id=command_id,
            status=ExecutionStatus.REQUESTED,
            occurred_at=occurred_at,
            revisions=revisions,
        )

    def transition_to(
        self,
        status: ExecutionStatus,
        *,
        occurred_at: datetime,
        revisions: RevisionVector | None = None,
        details: Mapping[str, JsonInput] | None = None,
        effect_refs: tuple[str, ...] | None = None,
        reason_code: str | None = None,
    ) -> ExecutionResult:
        validate_execution_transition(self.status, status)
        require_aware_datetime("occurred_at", occurred_at)
        if occurred_at < self.occurred_at:
            raise ValueError("occurred_at must not move backwards across execution transitions")
        return ExecutionResult(
            execution_id=self.execution_id,
            command_id=self.command_id,
            status=status,
            occurred_at=occurred_at,
            revisions=revisions or self.revisions,
            details=self.details if details is None else details,
            effect_refs=self.effect_refs if effect_refs is None else effect_refs,
            reason_code=reason_code,
            _transition_proof=_EXECUTION_TRANSITION_PROOF,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "command_id": self.command_id,
            "status": self.status.value,
            "occurred_at": self.occurred_at.isoformat(),
            "revisions": self.revisions.to_dict(),
            "details": jsonable(cast(JsonValue, self.details)),
            "effect_refs": list(self.effect_refs),
            "reason_code": self.reason_code,
        }


class AsyncResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"

    @property
    def is_committable(self) -> bool:
        return self is AsyncResultStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class AsyncWorkResult:
    request_id: str
    status: AsyncResultStatus
    completed_at: datetime
    revisions: RevisionVector
    started_at: datetime | None = None
    payload: JsonInput = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        require_non_empty("request_id", self.request_id)
        require_aware_datetime("completed_at", self.completed_at)
        if self.status is AsyncResultStatus.SUCCEEDED and self.started_at is None:
            raise ValueError("succeeded async work requires started_at")
        if self.started_at is not None:
            require_aware_datetime("started_at", self.started_at)
            if self.started_at > self.completed_at:
                raise ValueError("started_at must not be later than completed_at")
        if self.reason_code is not None:
            require_non_empty("reason_code", self.reason_code)
        object.__setattr__(self, "payload", freeze_json(self.payload))

    @property
    def is_committable(self) -> bool:
        return self.status.is_committable

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat(),
            "revisions": self.revisions.to_dict(),
            "payload": jsonable(cast(JsonValue, self.payload)),
            "reason_code": self.reason_code,
        }
