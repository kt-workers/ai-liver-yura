from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast

from .capabilities import CapabilityRequirement
from .common import (
    AuthorityRef,
    IntentRef,
    JsonInput,
    JsonValue,
    PreconditionRef,
    RevisionVector,
    freeze_json_mapping,
    jsonable,
    owned_tuple,
    require_aware_datetime,
    require_non_empty,
)


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    event_type: str
    source: str
    occurred_at: datetime
    trace_id: str
    revisions: RevisionVector
    payload: Mapping[str, JsonInput] = field(default_factory=dict)
    correlation_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        require_non_empty("event_id", self.event_id)
        require_non_empty("event_type", self.event_type)
        require_non_empty("source", self.source)
        require_non_empty("trace_id", self.trace_id)
        if self.correlation_id is not None:
            require_non_empty("correlation_id", self.correlation_id)
        if self.causation_event_id is not None:
            require_non_empty("causation_event_id", self.causation_event_id)
        require_aware_datetime("occurred_at", self.occurred_at)
        object.__setattr__(
            self,
            "payload",
            freeze_json_mapping("payload", self.payload),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "occurred_at": self.occurred_at.isoformat(),
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "causation_event_id": self.causation_event_id,
            "revisions": self.revisions.to_dict(),
            "payload": jsonable(cast(JsonValue, self.payload)),
        }


@dataclass(frozen=True, slots=True)
class ExecutiveDecision:
    decision_id: str
    created_at: datetime
    authority: AuthorityRef
    source_event_ids: tuple[str, ...]
    intent_refs: tuple[IntentRef, ...]
    revisions: RevisionVector

    def __post_init__(self) -> None:
        require_non_empty("decision_id", self.decision_id)
        require_aware_datetime("created_at", self.created_at)
        source_event_ids = owned_tuple("source_event_ids", self.source_event_ids)
        intent_refs = owned_tuple("intent_refs", self.intent_refs)
        object.__setattr__(self, "source_event_ids", source_event_ids)
        object.__setattr__(self, "intent_refs", intent_refs)
        if len(set(source_event_ids)) != len(source_event_ids):
            raise ValueError("source_event_ids must not contain duplicates")
        for event_id in source_event_ids:
            require_non_empty("source_event_id", event_id)
        intent_ids = [intent.intent_id for intent in intent_refs]
        if len(set(intent_ids)) != len(intent_ids):
            raise ValueError("intent_refs must not contain duplicate intent_id values")

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "created_at": self.created_at.isoformat(),
            "authority": self.authority.to_dict(),
            "source_event_ids": list(self.source_event_ids),
            "intent_refs": [intent.to_dict() for intent in self.intent_refs],
            "revisions": self.revisions.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SystemCommand:
    command_id: str
    decision_id: str
    intent_ref: IntentRef
    authority: AuthorityRef
    issued_at: datetime
    revisions: RevisionVector
    preconditions: tuple[PreconditionRef, ...] = ()
    required_capabilities: tuple[CapabilityRequirement, ...] = ()
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        require_non_empty("command_id", self.command_id)
        require_non_empty("decision_id", self.decision_id)
        require_aware_datetime("issued_at", self.issued_at)
        preconditions = owned_tuple("preconditions", self.preconditions)
        required_capabilities = owned_tuple(
            "required_capabilities",
            self.required_capabilities,
        )
        object.__setattr__(self, "preconditions", preconditions)
        object.__setattr__(self, "required_capabilities", required_capabilities)
        if self.deadline_at is not None:
            require_aware_datetime("deadline_at", self.deadline_at)
            if self.deadline_at <= self.issued_at:
                raise ValueError("deadline_at must be later than issued_at")
        precondition_ids = [item.precondition_id for item in preconditions]
        if len(set(precondition_ids)) != len(precondition_ids):
            raise ValueError("preconditions must not contain duplicate precondition_id values")

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "decision_id": self.decision_id,
            "intent_ref": self.intent_ref.to_dict(),
            "authority": self.authority.to_dict(),
            "issued_at": self.issued_at.isoformat(),
            "deadline_at": self.deadline_at.isoformat() if self.deadline_at else None,
            "revisions": self.revisions.to_dict(),
            "preconditions": [item.to_dict() for item in self.preconditions],
            "required_capabilities": [item.to_dict() for item in self.required_capabilities],
        }
