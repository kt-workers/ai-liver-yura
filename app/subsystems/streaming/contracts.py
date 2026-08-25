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


class StreamingSubsystemLifecycle(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"


class StreamingObservationSourceKind(str, Enum):
    PROVIDER_OBSERVATION = "provider_observation"
    USER_REPORT = "user_report"


class StreamingObservationReconciliation(str, Enum):
    UNRECONCILED = "unreconciled"
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"


class StreamingCommentModerationState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


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
class StreamingCapabilityView:
    """provider非依存の現在capability/descriptor世代。"""

    capability_id: str
    descriptor_revision: int
    operations: tuple[StreamingOperation, ...]
    available: bool
    provider_generation: int

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, "capability_id")
        require_revision(self.descriptor_revision, "descriptor_revision")
        require_revision(self.provider_generation, "provider_generation")
        if (
            not isinstance(self.operations, tuple)
            or not self.operations
            or any(not isinstance(operation, StreamingOperation) for operation in self.operations)
            or len(set(self.operations)) != len(self.operations)
            or type(self.available) is not bool
        ):
            raise ValueError("streaming capability が不正です")


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
        if self.started_at is not None and self.started_at > self.completed_at:
            raise ValueError("execution report time が不正です")
        allowed_effects = {
            StreamingExecutionStatus.SUCCEEDED: {StreamingEffectState.APPLIED},
            StreamingExecutionStatus.FAILED: {
                StreamingEffectState.NOT_APPLIED,
                StreamingEffectState.AMBIGUOUS,
                StreamingEffectState.UNKNOWN,
            },
            StreamingExecutionStatus.CANCELLED: {
                StreamingEffectState.AMBIGUOUS,
                StreamingEffectState.UNKNOWN,
            },
            StreamingExecutionStatus.TIMED_OUT: {
                StreamingEffectState.AMBIGUOUS,
                StreamingEffectState.UNKNOWN,
            },
            StreamingExecutionStatus.PROVIDER_UNAVAILABLE: {
                StreamingEffectState.NOT_APPLIED,
                StreamingEffectState.UNKNOWN,
            },
            StreamingExecutionStatus.UNKNOWN_EFFECT: {
                StreamingEffectState.AMBIGUOUS,
                StreamingEffectState.UNKNOWN,
            },
        }
        if self.effect_state not in allowed_effects[self.status]:
            raise ValueError("execution report effect truth が不正です")
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
    provider_generation: int | None
    trace_id: str | None = None
    reconciliation: StreamingObservationReconciliation = (
        StreamingObservationReconciliation.UNRECONCILED
    )

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
        if self.source_kind is StreamingObservationSourceKind.PROVIDER_OBSERVATION:
            require_revision(self.provider_generation, "provider_generation")
        elif self.provider_generation is not None:
            raise ValueError("user reportにprovider_generationは指定できません")
        if self.trace_id is not None:
            require_identifier(self.trace_id, "trace_id")
        require_aware(self.observed_at, "observed_at")
        if not isinstance(self.reconciliation, StreamingObservationReconciliation):
            raise ValueError("observation reconciliation が不正です")


@dataclass(frozen=True, slots=True)
class StreamingCommentEvent:
    event_id: str
    source_channel_ref: str
    text: str
    observed_at: datetime
    author_ref: str | None = None
    moderation_state: StreamingCommentModerationState = StreamingCommentModerationState.PENDING

    def __post_init__(self) -> None:
        for name in ("event_id", "source_channel_ref"):
            require_identifier(getattr(self, name), name)
        if self.author_ref is not None:
            require_identifier(self.author_ref, "author_ref")
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 500:
            raise ValueError("comment text が不正です")
        require_aware(self.observed_at, "observed_at")
        if not isinstance(self.moderation_state, StreamingCommentModerationState):
            raise ValueError("comment moderation state が不正です")


@dataclass(frozen=True, slots=True)
class StreamingCommentSignal:
    signal_id: str
    source_channel_ref: str
    representative_event_id: str
    count: int
    generated_at: datetime

    def __post_init__(self) -> None:
        for name in ("signal_id", "source_channel_ref", "representative_event_id"):
            require_identifier(getattr(self, name), name)
        if type(self.count) is not int or self.count < 1:
            raise ValueError("comment signal count が不正です")
        require_aware(self.generated_at, "generated_at")
