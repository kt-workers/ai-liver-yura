from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.contracts import CapabilityAvailability, EventEnvelope, RevisionVector
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
)


class InputModality(str, Enum):
    TEXT = "text"
    SPEECH = "speech"
    AUDIO = "audio"
    VISION = "vision"
    POINTER = "pointer"
    TOUCH = "touch"
    SUBSYSTEM = "subsystem"
    LIFECYCLE = "lifecycle"
    TIMER = "timer"


class InputPermission(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not_required"


class InputSessionPhase(str, Enum):
    START = "start"
    UPDATE = "update"
    END = "end"
    CANCEL = "cancel"


class ContactTargetKind(str, Enum):
    YURA_BODY = "yura_body"
    ENVIRONMENT = "environment"
    NONE = "none"
    UNKNOWN = "unknown"


class InputAdmissionStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class InputRejectionReason(str, Enum):
    DUPLICATE = "duplicate"
    SOURCE_UNAVAILABLE = "source_unavailable"
    PERMISSION_DENIED = "permission_denied"
    PERMISSION_UNKNOWN = "permission_unknown"
    SESSION_ALREADY_EXISTS = "session_already_exists"
    SESSION_NOT_ACTIVE = "session_not_active"
    SESSION_TERMINATED = "session_terminated"
    SESSION_SEQUENCE_OUT_OF_ORDER = "session_sequence_out_of_order"


@dataclass(frozen=True, slots=True)
class InputSourceLifecycleChange:
    previous_availability: CapabilityAvailability
    previous_permission: InputPermission
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.reason_code is not None:
            require_identifier(self.reason_code, "reason_code")

    def to_dict(self) -> dict[str, object]:
        return {
            "previous_availability": self.previous_availability.value,
            "previous_permission": self.previous_permission.value,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class InputSourceState:
    source_id: str
    source_kind: str
    availability: CapabilityAvailability
    permission: InputPermission
    capability_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.source_id, "source_id")
        require_identifier(self.source_kind, "source_kind")
        if self.capability_id is not None:
            require_identifier(self.capability_id, "capability_id")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "availability": self.availability.value,
            "permission": self.permission.value,
            "capability_id": self.capability_id,
        }


@dataclass(frozen=True, slots=True)
class InputSessionSample:
    session_id: str
    phase: InputSessionPhase
    sequence: int

    def __post_init__(self) -> None:
        require_identifier(self.session_id, "session_id")
        require_revision(self.sequence, "sequence")

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "sequence": self.sequence,
        }


@dataclass(frozen=True, slots=True)
class PointerSample:
    x: float
    y: float
    pressure: float | None = None
    buttons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (("x", self.x), ("y", self.y)):
            if type(value) not in (int, float) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.pressure is not None and (
            type(self.pressure) not in (int, float) or not 0.0 <= self.pressure <= 1.0
        ):
            raise ValueError("pressure must be between 0 and 1")
        buttons = tuple(self.buttons)
        if any(not isinstance(item, str) or not item.strip() for item in buttons):
            raise ValueError("buttons must contain non-empty strings")
        if len(set(buttons)) != len(buttons):
            raise ValueError("buttons must be unique")
        object.__setattr__(self, "buttons", buttons)

    def to_dict(self) -> dict[str, object]:
        return {"x": self.x, "y": self.y, "pressure": self.pressure, "buttons": list(self.buttons)}


@dataclass(frozen=True, slots=True)
class ContactPercept:
    target_kind: ContactTargetKind
    confidence: float
    percept_capability_id: str
    percept_revision: int
    body_region: str | None = None

    def __post_init__(self) -> None:
        if type(self.confidence) not in (int, float) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        require_identifier(self.percept_capability_id, "percept_capability_id")
        require_revision(self.percept_revision, "percept_revision")
        if self.body_region is not None:
            require_identifier(self.body_region, "body_region")
        if self.target_kind is ContactTargetKind.YURA_BODY and self.body_region is None:
            raise ValueError("yura_body contact requires body_region")
        if self.target_kind is not ContactTargetKind.YURA_BODY and self.body_region:
            raise ValueError("only yura_body contact can have body_region")

    def to_dict(self) -> dict[str, object]:
        return {
            "target_kind": self.target_kind.value,
            "body_region": self.body_region,
            "confidence": self.confidence,
            "percept_capability_id": self.percept_capability_id,
            "percept_revision": self.percept_revision,
        }


@dataclass(frozen=True, slots=True)
class InputObservation:
    observation_id: str
    source: InputSourceState
    modality: InputModality
    semantic_unit: str
    observed_at: datetime
    trace_id: str
    revisions: RevisionVector
    payload: JsonValue
    correlation_id: str | None = None
    causation_event_id: str | None = None
    session: InputSessionSample | None = None
    pointer: PointerSample | None = None
    contact: ContactPercept | None = None
    lifecycle_change: InputSourceLifecycleChange | None = None

    def __post_init__(self) -> None:
        require_identifier(self.observation_id, "observation_id")
        require_identifier(self.semantic_unit, "semantic_unit")
        require_identifier(self.trace_id, "trace_id")
        require_aware(self.observed_at, "observed_at")
        for name in ("correlation_id", "causation_event_id"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        if (self.pointer is not None or self.contact is not None) and self.modality not in (
            InputModality.POINTER,
            InputModality.TOUCH,
        ):
            raise ValueError("pointer and contact are only valid for pointer or touch modality")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        if self.modality is InputModality.LIFECYCLE:
            if self.semantic_unit != "source_state_changed":
                raise ValueError("lifecycle semantic_unit must be source_state_changed")
            if self.lifecycle_change is None:
                raise ValueError("lifecycle observation requires lifecycle_change")
            if self.session is not None or self.pointer is not None or self.contact is not None:
                raise ValueError("lifecycle observation cannot carry session, pointer, or contact")
            if not isinstance(self.payload, Mapping) or self.payload:
                raise ValueError("lifecycle observation payload must be an empty object")
            if (
                self.lifecycle_change.previous_availability is self.source.availability
                and self.lifecycle_change.previous_permission is self.source.permission
            ):
                raise ValueError(
                    "lifecycle observation must describe an actual source state change"
                )
        elif self.lifecycle_change is not None:
            raise ValueError("lifecycle_change is only valid for lifecycle modality")


@dataclass(frozen=True, slots=True)
class NormalizedInputEvent:
    envelope: EventEnvelope
    modality: InputModality
    source: InputSourceState
    session: InputSessionSample | None = None
    pointer: PointerSample | None = None
    contact: ContactPercept | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "envelope": self.envelope.to_dict(),
            "modality": self.modality.value,
            "source": self.source.to_dict(),
            "session": None if self.session is None else self.session.to_dict(),
            "pointer": None if self.pointer is None else self.pointer.to_dict(),
            "contact": None if self.contact is None else self.contact.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class InputAdmission:
    status: InputAdmissionStatus
    event: NormalizedInputEvent | None = None
    reason: InputRejectionReason | None = None

    def __post_init__(self) -> None:
        if self.status is InputAdmissionStatus.ACCEPTED:
            if self.event is None or self.reason is not None:
                raise ValueError("accepted admission requires only an event")
        elif self.event is not None or self.reason is None:
            raise ValueError("non-accepted admission requires only a reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "event": None if self.event is None else self.event.to_dict(),
            "reason": None if self.reason is None else self.reason.value,
        }


def observation_payload(observation: InputObservation) -> JsonValue:
    return freeze_json(
        {
            "modality": observation.modality.value,
            "source": observation.source.to_dict(),
            "session": None if observation.session is None else observation.session.to_dict(),
            "pointer": None if observation.pointer is None else observation.pointer.to_dict(),
            "contact": None if observation.contact is None else observation.contact.to_dict(),
            "lifecycle_change": None
            if observation.lifecycle_change is None
            else observation.lifecycle_change.to_dict(),
            "content": thaw_json(observation.payload),
        }
    )
