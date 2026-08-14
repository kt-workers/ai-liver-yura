from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TypeVar, cast

from app.domain.contracts import (
    AuthorityRef,
    CapabilityDescriptor,
    CapabilityRequirement,
    ExecutionResult,
    ExecutionStatus,
    IntentKind,
    IntentRef,
    PreconditionRef,
    RevisionVector,
    SystemCommand,
)
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    thaw_json,
    timestamp_to_json,
    utc_instant,
)


class ActivityInterruptibility(str, Enum):
    INTERRUPTIBLE = "interruptible"
    SOFT_CANCEL_ONLY = "soft_cancel_only"
    NON_INTERRUPTIBLE = "non_interruptible"


class ExecutionEffectKind(str, Enum):
    OBSERVABLE = "observable"
    APPLIED = "applied"


_EXECUTABLE_INTENT_KINDS = frozenset(
    {
        IntentKind.SPEECH,
        IntentKind.BODY,
        IntentKind.ACTIVITY,
        IntentKind.PLUGIN,
        IntentKind.SYSTEM,
    }
)


T = TypeVar("T")


def _owned(values: object, expected: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    result = tuple(values)
    if any(not isinstance(item, expected) for item in result):
        raise ValueError(f"{name} contains an invalid value")
    return cast(tuple[T, ...], result)


def _ids(values: object, name: str) -> tuple[str, ...]:
    result = _owned(values, str, name)
    if any(not item.strip() for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    return result


@dataclass(frozen=True, slots=True)
class ActivityInvocation:
    invocation_id: str
    command: SystemCommand
    operation_ref: str
    arguments: JsonValue
    interruptibility: ActivityInterruptibility
    requested_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.invocation_id, "invocation_id")
        if not isinstance(self.command, SystemCommand):
            raise ValueError("command must be SystemCommand")
        if not isinstance(self.command.intent_ref, IntentRef):
            raise ValueError("command intent_ref must be IntentRef")
        if not isinstance(self.command.authority, AuthorityRef):
            raise ValueError("command authority must be AuthorityRef")
        if not isinstance(self.command.revisions, RevisionVector):
            raise ValueError("command revisions must be RevisionVector")
        if self.command.intent_ref.kind not in _EXECUTABLE_INTENT_KINDS:
            raise ValueError("command intent kind is not executable")
        preconditions = _owned(self.command.preconditions, PreconditionRef, "command preconditions")
        requirements = _owned(
            self.command.required_capabilities,
            CapabilityRequirement,
            "command required_capabilities",
        )
        if len({item.precondition_id for item in preconditions}) != len(preconditions):
            raise ValueError("command precondition ids must be unique")
        if len(set(requirements)) != len(requirements):
            raise ValueError("command capability requirements must be unique")
        require_identifier(self.operation_ref, "operation_ref")
        arguments = freeze_json(self.arguments)
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be an object")
        object.__setattr__(self, "arguments", arguments)
        if not isinstance(self.interruptibility, ActivityInterruptibility):
            raise ValueError("interruptibility must be ActivityInterruptibility")
        require_aware(self.requested_at, "requested_at")
        if utc_instant(self.requested_at) < utc_instant(self.command.issued_at):
            raise ValueError("invocation cannot predate command")

    def to_dict(self) -> dict[str, object]:
        return {
            "invocation_id": self.invocation_id,
            "command": self.command.to_dict(),
            "operation_ref": self.operation_ref,
            "arguments": thaw_json(self.arguments),
            "interruptibility": self.interruptibility.value,
            "requested_at": timestamp_to_json(self.requested_at),
        }


@dataclass(frozen=True, slots=True)
class ExecutionPreconditionState:
    precondition_id: str
    subject_ref: str
    predicate: str
    actual: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.precondition_id, "precondition_id")
        require_identifier(self.subject_ref, "subject_ref")
        require_identifier(self.predicate, "predicate")
        object.__setattr__(self, "actual", freeze_json(self.actual))


@dataclass(frozen=True, slots=True)
class ExecutionPreflightSnapshot:
    revisions: RevisionVector
    capabilities: tuple[CapabilityDescriptor, ...]
    preconditions: tuple[ExecutionPreconditionState, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions must be RevisionVector")
        for name, item_type in (
            ("capabilities", CapabilityDescriptor),
            ("preconditions", ExecutionPreconditionState),
        ):
            object.__setattr__(self, name, _owned(getattr(self, name), item_type, name))
        for values, attribute, name in (
            (self.capabilities, "capability_id", "capability ids"),
            (self.preconditions, "precondition_id", "precondition ids"),
        ):
            identifiers = [getattr(item, attribute) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} must be unique")
        require_aware(self.captured_at, "captured_at")


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    requirement: CapabilityRequirement
    capability_id: str
    descriptor_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, CapabilityRequirement):
            raise ValueError("requirement must be CapabilityRequirement")
        require_identifier(self.capability_id, "capability_id")
        if type(self.descriptor_revision) is not int or self.descriptor_revision < 0:
            raise ValueError("descriptor_revision must be a non-negative int")


@dataclass(frozen=True, slots=True)
class ExecutionEffectEvidence:
    effect_id: str
    capability_id: str
    descriptor_revision: int
    operation_ref: str
    kind: ExecutionEffectKind
    payload: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.effect_id, "effect_id")
        require_identifier(self.capability_id, "capability_id")
        if type(self.descriptor_revision) is not int or self.descriptor_revision < 0:
            raise ValueError("descriptor_revision must be a non-negative int")
        require_identifier(self.operation_ref, "operation_ref")
        if not isinstance(self.kind, ExecutionEffectKind):
            raise ValueError("kind must be ExecutionEffectKind")
        payload = freeze_json(self.payload)
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be an object")
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class ExecutionAdapterReport:
    command_id: str
    invocation_id: str
    dispatch_id: str
    status: ExecutionStatus
    occurred_at: datetime
    details: JsonValue
    effects: tuple[ExecutionEffectEvidence, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.command_id, "command_id")
        require_identifier(self.invocation_id, "invocation_id")
        require_identifier(self.dispatch_id, "dispatch_id")
        allowed = {
            ExecutionStatus.OBSERVABLE,
            ExecutionStatus.APPLIED,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
        }
        if not isinstance(self.status, ExecutionStatus) or self.status not in allowed:
            raise ValueError("adapter report status is not allowed")
        require_aware(self.occurred_at, "occurred_at")
        details = freeze_json(self.details)
        if not isinstance(details, Mapping):
            raise ValueError("details must be an object")
        object.__setattr__(self, "details", details)
        effects = _owned(self.effects, ExecutionEffectEvidence, "effects")
        if len({item.effect_id for item in effects}) != len(effects):
            raise ValueError("effect ids must be unique")
        if effects and self.status not in {
            ExecutionStatus.OBSERVABLE,
            ExecutionStatus.APPLIED,
            ExecutionStatus.COMPLETED,
        }:
            raise ValueError("terminal failure report cannot introduce effects")
        if self.status is ExecutionStatus.OBSERVABLE and any(
            item.kind is ExecutionEffectKind.APPLIED for item in effects
        ):
            raise ValueError("observable report cannot introduce applied effect")
        object.__setattr__(self, "effects", effects)


@dataclass(frozen=True, slots=True)
class ExecutionDispatchRequest:
    dispatch_id: str
    invocation: ActivityInvocation
    accepted_result: ExecutionResult
    bindings: tuple[CapabilityBinding, ...]

    def __post_init__(self) -> None:
        require_identifier(self.dispatch_id, "dispatch_id")
        if not isinstance(self.invocation, ActivityInvocation):
            raise ValueError("invocation must be ActivityInvocation")
        if not isinstance(self.accepted_result, ExecutionResult):
            raise ValueError("accepted_result must be ExecutionResult")
        if self.accepted_result.command_id != self.invocation.command.command_id:
            raise ValueError("accepted result command does not match invocation")
        if self.accepted_result.status is not ExecutionStatus.ACCEPTED:
            raise ValueError("dispatch requires accepted execution result")
        object.__setattr__(self, "bindings", _owned(self.bindings, CapabilityBinding, "bindings"))


@dataclass(frozen=True, slots=True)
class ActivityExecutionRecord:
    invocation: ActivityInvocation
    bindings: tuple[CapabilityBinding, ...]
    result: ExecutionResult
    dispatch_id: str | None = None
    cancellation_reason: str | None = None
    cancellation_requested_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.invocation, ActivityInvocation):
            raise ValueError("invocation must be ActivityInvocation")
        object.__setattr__(self, "bindings", _owned(self.bindings, CapabilityBinding, "bindings"))
        if not isinstance(self.result, ExecutionResult):
            raise ValueError("result must be ExecutionResult")
        if self.result.command_id != self.invocation.command.command_id:
            raise ValueError("result command does not match invocation")
        if self.result.revisions != self.invocation.command.revisions:
            raise ValueError("result revisions do not match command")
        if self.dispatch_id is not None:
            require_identifier(self.dispatch_id, "dispatch_id")
        if (self.cancellation_reason is None) != (self.cancellation_requested_at is None):
            raise ValueError("cancellation reason and timestamp must appear together")
        if self.cancellation_reason is not None:
            require_identifier(self.cancellation_reason, "cancellation_reason")
            assert self.cancellation_requested_at is not None
            require_aware(self.cancellation_requested_at, "cancellation_requested_at")

    @property
    def terminal(self) -> bool:
        return self.result.status in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.UNSUPPORTED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.SUPERSEDED,
        }
