from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .capabilities import CapabilityRequirement
from .common import (
    AuthorityRef,
    IntentRef,
    JsonValue,
    PreconditionRef,
    RevisionVector,
    freeze_json,
    require_aware,
    require_identifier,
    thaw_json,
    timestamp_to_json,
    utc_instant,
)


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    event_type: str
    source: str
    occurred_at: datetime
    trace_id: str
    revisions: RevisionVector
    payload: JsonValue
    correlation_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("event_id", "event_type", "source", "trace_id"):
            require_identifier(getattr(self, field_name), field_name)
        for field_name in ("correlation_id", "causation_event_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name)
        require_aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "occurred_at": timestamp_to_json(self.occurred_at),
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "causation_event_id": self.causation_event_id,
            "revisions": self.revisions.to_dict(),
            "payload": thaw_json(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ExecutiveDecision:
    decision_id: str
    source_event_ids: tuple[str, ...]
    intent_refs: tuple[IntentRef, ...]
    authority: AuthorityRef
    revisions: RevisionVector
    created_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.decision_id, "decision_id")
        source_event_ids = tuple(self.source_event_ids)
        if any(not isinstance(item, str) or not item.strip() for item in source_event_ids):
            raise ValueError("source_event_ids must contain non-empty strings")
        if len(set(source_event_ids)) != len(source_event_ids):
            raise ValueError("source_event_ids must be unique")
        object.__setattr__(self, "source_event_ids", source_event_ids)
        object.__setattr__(self, "intent_refs", tuple(self.intent_refs))
        require_aware(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "source_event_ids": list(self.source_event_ids),
            "intent_refs": [item.to_dict() for item in self.intent_refs],
            "authority": self.authority.to_dict(),
            "revisions": self.revisions.to_dict(),
            "created_at": timestamp_to_json(self.created_at),
        }


@dataclass(frozen=True, slots=True)
class SystemCommand:
    command_id: str
    decision_id: str
    intent_ref: IntentRef
    authority: AuthorityRef
    issued_at: datetime
    revisions: RevisionVector
    deadline_at: datetime | None = None
    preconditions: tuple[PreconditionRef, ...] = ()
    required_capabilities: tuple[CapabilityRequirement, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.command_id, "command_id")
        require_identifier(self.decision_id, "decision_id")
        require_aware(self.issued_at, "issued_at")
        if self.deadline_at is not None:
            require_aware(self.deadline_at, "deadline_at")
            if utc_instant(self.deadline_at) <= utc_instant(self.issued_at):
                raise ValueError("deadline_at must be later than issued_at")
        object.__setattr__(self, "preconditions", tuple(self.preconditions))
        object.__setattr__(self, "required_capabilities", tuple(self.required_capabilities))

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "decision_id": self.decision_id,
            "intent_ref": self.intent_ref.to_dict(),
            "authority": self.authority.to_dict(),
            "issued_at": timestamp_to_json(self.issued_at),
            "deadline_at": None
            if self.deadline_at is None
            else timestamp_to_json(self.deadline_at),
            "revisions": self.revisions.to_dict(),
            "preconditions": [item.to_dict() for item in self.preconditions],
            "required_capabilities": [item.to_dict() for item in self.required_capabilities],
        }
