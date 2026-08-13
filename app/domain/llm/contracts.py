from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.contracts.common import (
    JsonValue,
    PreconditionRef,
    RevisionVector,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
    timestamp_to_json,
    utc_instant,
)


class LLMActivationPolicy(str, Enum):
    REQUIRED = "required"
    CONDITIONAL = "conditional"
    OPTIONAL = "optional"
    BACKGROUND = "background"


class LLMFailurePolicy(str, Enum):
    FAIL_CLOSED = "fail_closed"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"
    SKIP_OPTIONAL = "skip_optional"
    RETRY_BOUNDED = "retry_bounded"


class LLMModelClass(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP_REASONING = "deep_reasoning"
    MULTIMODAL = "multimodal"


class LLMReasoningEffort(str, Enum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LLMPriority(str, Enum):
    FOREGROUND = "foreground"
    NORMAL = "normal"
    BACKGROUND = "background"


class LLMInterruptibility(str, Enum):
    INTERRUPTIBLE = "interruptible"
    SOFT_CANCEL_ONLY = "soft_cancel_only"
    NON_INTERRUPTIBLE = "non_interruptible"


class LLMStalePolicy(str, Enum):
    REJECT = "reject"
    MARK_STALE = "mark_stale"
    REVALIDATE = "revalidate"


class LLMRoleStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class LLMFailureCode(str, Enum):
    SCHEMA_INVALID = "schema_invalid"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    POLICY_VIOLATION = "policy_violation"


_STATUS_FAILURE: dict[LLMRoleStatus, frozenset[LLMFailureCode]] = {
    LLMRoleStatus.FAILED: frozenset(
        {
            LLMFailureCode.SCHEMA_INVALID,
            LLMFailureCode.PROVIDER_UNAVAILABLE,
            LLMFailureCode.PROVIDER_ERROR,
            LLMFailureCode.POLICY_VIOLATION,
        }
    ),
    LLMRoleStatus.CANCELLED: frozenset({LLMFailureCode.CANCELLED}),
    LLMRoleStatus.TIMED_OUT: frozenset({LLMFailureCode.TIMEOUT}),
    LLMRoleStatus.STALE: frozenset({LLMFailureCode.STALE}),
    LLMRoleStatus.SUPERSEDED: frozenset({LLMFailureCode.SUPERSEDED}),
    LLMRoleStatus.REJECTED: frozenset({LLMFailureCode.REJECTED}),
}


def _strict_positive_number(value: float, field_name: str) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be a positive number")


@dataclass(frozen=True, slots=True)
class StructuredPayload:
    schema_id: str
    value: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.schema_id, "schema_id")
        frozen = freeze_json(self.value)
        if not isinstance(frozen, dict) and not hasattr(frozen, "items"):
            raise ValueError("structured payload value must be a JSON object")
        object.__setattr__(self, "value", frozen)

    def to_dict(self) -> dict[str, object]:
        return {"schema_id": self.schema_id, "value": thaw_json(self.value)}


@dataclass(frozen=True, slots=True)
class LLMExecutionPolicy:
    model_class: LLMModelClass
    reasoning_effort: LLMReasoningEffort
    timeout_seconds: float
    max_attempts: int
    max_output_tokens: int
    temperature: float | None = None

    def __post_init__(self) -> None:
        _strict_positive_number(self.timeout_seconds, "timeout_seconds")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive int")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive int")
        if self.temperature is not None:
            if (
                type(self.temperature) not in (int, float)
                or not isfinite(self.temperature)
                or not 0 <= self.temperature <= 2
            ):
                raise ValueError("temperature must be between 0 and 2")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_class": self.model_class.value,
            "reasoning_effort": self.reasoning_effort.value,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
        }


@dataclass(frozen=True, slots=True)
class LLMRoleDescriptor:
    role_id: str
    responsibility: str
    input_schema_id: str
    output_schema_id: str
    authority_scope: str
    activation: LLMActivationPolicy
    failure_policy: LLMFailurePolicy
    default_execution_policy: LLMExecutionPolicy

    def __post_init__(self) -> None:
        for name in (
            "role_id",
            "responsibility",
            "input_schema_id",
            "output_schema_id",
            "authority_scope",
        ):
            require_identifier(getattr(self, name), name)

    def to_dict(self) -> dict[str, object]:
        return {
            "role_id": self.role_id,
            "responsibility": self.responsibility,
            "input_schema_id": self.input_schema_id,
            "output_schema_id": self.output_schema_id,
            "authority_scope": self.authority_scope,
            "activation": self.activation.value,
            "failure_policy": self.failure_policy.value,
            "default_execution_policy": self.default_execution_policy.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LLMRoleRequest:
    request_id: str
    role_id: str
    input: StructuredPayload
    source_event_ids: tuple[str, ...]
    revisions: RevisionVector
    preconditions: tuple[PreconditionRef, ...]
    priority: LLMPriority
    interruptibility: LLMInterruptibility
    stale_policy: LLMStalePolicy
    execution_policy: LLMExecutionPolicy
    created_at: datetime
    trace_id: str
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "role_id", "trace_id"):
            require_identifier(getattr(self, name), name)
        source_event_ids = tuple(self.source_event_ids)
        if any(not isinstance(item, str) or not item.strip() for item in source_event_ids):
            raise ValueError("source_event_ids must contain non-empty strings")
        if len(set(source_event_ids)) != len(source_event_ids):
            raise ValueError("source_event_ids must be unique")
        object.__setattr__(self, "source_event_ids", source_event_ids)
        object.__setattr__(self, "preconditions", tuple(self.preconditions))
        require_aware(self.created_at, "created_at")
        if self.deadline_at is not None:
            require_aware(self.deadline_at, "deadline_at")
            if utc_instant(self.deadline_at) <= utc_instant(self.created_at):
                raise ValueError("deadline_at must be later than created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "role_id": self.role_id,
            "input": self.input.to_dict(),
            "source_event_ids": list(self.source_event_ids),
            "revisions": self.revisions.to_dict(),
            "preconditions": [item.to_dict() for item in self.preconditions],
            "priority": self.priority.value,
            "interruptibility": self.interruptibility.value,
            "stale_policy": self.stale_policy.value,
            "execution_policy": self.execution_policy.to_dict(),
            "created_at": timestamp_to_json(self.created_at),
            "deadline_at": None
            if self.deadline_at is None
            else timestamp_to_json(self.deadline_at),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class LLMRoleFailure:
    code: LLMFailureCode
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.message, "message")

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code.value, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True, slots=True)
class LLMTokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        require_revision(self.input_tokens, "input_tokens")
        require_revision(self.output_tokens, "output_tokens")

    def to_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass(frozen=True, slots=True)
class LLMRoleResult:
    request_id: str
    role_id: str
    status: LLMRoleStatus
    revisions: RevisionVector
    completed_at: datetime
    trace_id: str
    model_class: LLMModelClass
    attempt_count: int
    token_usage: LLMTokenUsage
    output: StructuredPayload | None = None
    failure: LLMRoleFailure | None = None
    started_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "role_id", "trace_id"):
            require_identifier(getattr(self, name), name)
        require_aware(self.completed_at, "completed_at")
        if self.started_at is not None:
            require_aware(self.started_at, "started_at")
            if utc_instant(self.started_at) > utc_instant(self.completed_at):
                raise ValueError("started_at cannot be later than completed_at")
        if type(self.attempt_count) is not int or self.attempt_count < 0:
            raise ValueError("attempt_count must be a non-negative int")
        if self.status is LLMRoleStatus.SUCCEEDED:
            if self.started_at is None or self.output is None or self.failure is not None:
                raise ValueError("succeeded result requires start and output without failure")
        else:
            if self.output is not None or self.failure is None:
                raise ValueError("non-success result requires failure without output")
            if self.failure.code not in _STATUS_FAILURE[self.status]:
                raise ValueError("failure code does not match result status")

    @property
    def is_committable(self) -> bool:
        return self.status is LLMRoleStatus.SUCCEEDED

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "role_id": self.role_id,
            "status": self.status.value,
            "revisions": self.revisions.to_dict(),
            "started_at": None
            if self.started_at is None
            else timestamp_to_json(self.started_at),
            "completed_at": timestamp_to_json(self.completed_at),
            "trace_id": self.trace_id,
            "model_class": self.model_class.value,
            "attempt_count": self.attempt_count,
            "token_usage": self.token_usage.to_dict(),
            "output": None if self.output is None else self.output.to_dict(),
            "failure": None if self.failure is None else self.failure.to_dict(),
        }


def validate_role_exchange(
    descriptor: LLMRoleDescriptor,
    request: LLMRoleRequest,
    result: LLMRoleResult,
) -> LLMRoleFailure | None:
    """Validate transport identity without granting Domain commit authority."""
    if request.role_id != descriptor.role_id:
        return LLMRoleFailure(
            LLMFailureCode.POLICY_VIOLATION,
            "request role does not match role descriptor",
        )
    if request.input.schema_id != descriptor.input_schema_id:
        return LLMRoleFailure(
            LLMFailureCode.SCHEMA_INVALID,
            "request input schema does not match role descriptor",
        )
    if result.request_id != request.request_id or result.role_id != request.role_id:
        return LLMRoleFailure(
            LLMFailureCode.POLICY_VIOLATION,
            "result identity does not match request",
        )
    if result.trace_id != request.trace_id or result.revisions != request.revisions:
        return LLMRoleFailure(
            LLMFailureCode.POLICY_VIOLATION,
            "result trace or revisions do not match request",
        )
    request_instant = utc_instant(request.created_at)
    if utc_instant(result.completed_at) < request_instant or (
        result.started_at is not None and utc_instant(result.started_at) < request_instant
    ):
        return LLMRoleFailure(
            LLMFailureCode.POLICY_VIOLATION,
            "result timing predates request creation",
        )
    if (
        result.status is LLMRoleStatus.SUCCEEDED
        and result.output is not None
        and result.output.schema_id != descriptor.output_schema_id
    ):
        return LLMRoleFailure(
            LLMFailureCode.SCHEMA_INVALID,
            "result output schema does not match role descriptor",
        )
    return None
