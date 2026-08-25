from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
)


class StreamingOperation(str, Enum):
    PREPARE_STREAM = "prepare_stream"
    START_STREAM = "start_stream"
    END_STREAM = "end_stream"
    QUERY_STREAM_STATUS = "query_stream_status"


class StreamingExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNKNOWN_EFFECT = "unknown_effect"


class StreamingEffectState(str, Enum):
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class StreamingExternalState(str, Enum):
    UNAVAILABLE = "unavailable"
    NOT_PREPARED = "not_prepared"
    PREPARING = "preparing"
    READY = "ready"
    STARTING = "starting"
    LIVE = "live"
    ENDING = "ending"
    ENDED = "ended"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class StreamingObservationSourceKind(str, Enum):
    PROVIDER_OBSERVATION = "provider_observation"
    USER_REPORT = "user_report"


def _refs(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if (
        not isinstance(values, tuple)
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"{name} が不正です")
    return values


@dataclass(frozen=True, slots=True)
class StreamingExecutionRequest:
    execution_id: str
    activity_id: str
    capability_id: str
    descriptor_revision: int
    operation: StreamingOperation
    source_context_revision: int
    trace_id: str
    goal_revision: int | None = None
    attention_revision: int | None = None
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        for field in ("execution_id", "activity_id", "capability_id", "trace_id"):
            require_identifier(getattr(self, field), field)
        for field in (
            "descriptor_revision",
            "source_context_revision",
            "goal_revision",
            "attention_revision",
        ):
            require_revision(
                getattr(self, field),
                field,
                optional=field.endswith("revision") and getattr(self, field) is None,
            )
        if not isinstance(self.operation, StreamingOperation):
            raise ValueError("operation が不正です")
        if self.deadline_at is not None:
            require_aware(self.deadline_at, "deadline_at")


@dataclass(frozen=True, slots=True)
class StreamingExecutionReport:
    execution_id: str
    operation: StreamingOperation
    status: StreamingExecutionStatus
    effect_state: StreamingEffectState
    completed_at: datetime
    observation_refs: tuple[str, ...]
    retryable: bool
    sanitized_diagnostics: tuple[str, ...] = ()
    started_at: datetime | None = None

    def __post_init__(self) -> None:
        require_identifier(self.execution_id, "execution_id")
        if (
            not isinstance(self.operation, StreamingOperation)
            or not isinstance(self.status, StreamingExecutionStatus)
            or not isinstance(self.effect_state, StreamingEffectState)
            or type(self.retryable) is not bool
        ):
            raise ValueError("execution report が不正です")
        if self.started_at is not None:
            require_aware(self.started_at, "started_at")
        require_aware(self.completed_at, "completed_at")
        object.__setattr__(
            self, "observation_refs", _refs(self.observation_refs, "observation_refs")
        )
        object.__setattr__(
            self,
            "sanitized_diagnostics",
            _refs(self.sanitized_diagnostics, "sanitized_diagnostics"),
        )


@dataclass(frozen=True, slots=True)
class StreamingExternalObservation:
    observation_id: str
    state: StreamingExternalState
    source_kind: StreamingObservationSourceKind
    source_ref: str
    observed_at: datetime
    confidence: float
    provider_generation: int
    trace_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("observation_id", "source_ref"):
            require_identifier(getattr(self, field), field)
        if not isinstance(self.state, StreamingExternalState) or not isinstance(
            self.source_kind, StreamingObservationSourceKind
        ):
            raise ValueError("observation が不正です")
        if (
            type(self.confidence) not in (int, float)
            or not isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence が不正です")
        object.__setattr__(self, "confidence", float(self.confidence))
        require_revision(self.provider_generation, "provider_generation")
        if self.trace_id is not None:
            require_identifier(self.trace_id, "trace_id")
        require_aware(self.observed_at, "observed_at")
