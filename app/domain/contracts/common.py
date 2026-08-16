from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


def require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def require_revision(value: int | None, field_name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if type(value) is not int:
        raise ValueError(f"{field_name} must be a non-negative int")
    assert isinstance(value, int)
    if value < 0:
        raise ValueError(f"{field_name} must be a non-negative int")


def require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def utc_instant(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def freeze_json(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            frozen[key] = freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise ValueError(f"unsupported JSON value type: {type(value).__name__}")


def thaw_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def timestamp_to_json(value: datetime) -> str:
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class RevisionVector:
    source_context_revision: int
    goal_revision: int | None = None
    attention_revision: int | None = None

    def __post_init__(self) -> None:
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.goal_revision, "goal_revision", optional=True)
        require_revision(self.attention_revision, "attention_revision", optional=True)

    def to_dict(self) -> dict[str, int | None]:
        return {
            "source_context_revision": self.source_context_revision,
            "goal_revision": self.goal_revision,
            "attention_revision": self.attention_revision,
        }


class SourceLifecycleOperation(str, Enum):
    OPEN = "open"
    REFRESH = "refresh"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class AuthorityRef:
    owner: str
    scope: str
    reference_id: str

    def __post_init__(self) -> None:
        require_identifier(self.owner, "owner")
        require_identifier(self.scope, "scope")
        require_identifier(self.reference_id, "reference_id")

    def to_dict(self) -> dict[str, str]:
        return {"owner": self.owner, "scope": self.scope, "reference_id": self.reference_id}


@dataclass(frozen=True, slots=True)
class PreconditionRef:
    precondition_id: str
    predicate: str
    subject_ref: str
    expected: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.precondition_id, "precondition_id")
        require_identifier(self.predicate, "predicate")
        require_identifier(self.subject_ref, "subject_ref")
        object.__setattr__(self, "expected", freeze_json(self.expected))

    def to_dict(self) -> dict[str, object]:
        return {
            "precondition_id": self.precondition_id,
            "predicate": self.predicate,
            "subject_ref": self.subject_ref,
            "expected": thaw_json(self.expected),
        }


class IntentKind(str, Enum):
    SPEECH = "speech"
    BODY = "body"
    ACTIVITY = "activity"
    PLUGIN = "plugin"
    ATTENTION = "attention"
    GOAL_TRANSITION = "goal_transition"
    COMMITMENT_TRANSITION = "commitment_transition"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class IntentRef:
    kind: IntentKind
    intent_id: str

    def __post_init__(self) -> None:
        require_identifier(self.intent_id, "intent_id")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "intent_id": self.intent_id}
