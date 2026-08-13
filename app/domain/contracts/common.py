from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias, TypeVar, cast

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
JsonInput: TypeAlias = JsonScalar | Sequence["JsonInput"] | Mapping[str, "JsonInput"]

_T = TypeVar("_T")


def require_non_empty(name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def require_aware_datetime(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def owned_tuple(name: str, value: Sequence[_T]) -> tuple[_T, ...]:
    """Take an owned immutable copy of a tuple-valued contract field."""
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a non-string sequence")
    if not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence")
    return tuple(value)


def freeze_json(value: JsonInput) -> JsonValue:
    """Convert JSON-like data into an immutable representation."""
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("JSON float values must be finite")
        return value
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            frozen[key] = freeze_json(item)
        return cast(Mapping[str, JsonValue], MappingProxyType(frozen))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def freeze_json_mapping(
    name: str,
    value: Mapping[str, JsonInput],
) -> Mapping[str, JsonValue]:
    """Freeze a mapping while preserving the mapping contract at runtime."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return cast(Mapping[str, JsonValue], freeze_json(value))


def jsonable(value: JsonValue) -> object:
    """Convert an immutable JsonValue to values accepted by json.dumps."""
    if isinstance(value, Mapping):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    return value


class RevisionKind(str, Enum):
    SOURCE_CONTEXT = "source_context"
    GOAL = "goal"
    ATTENTION = "attention"


@dataclass(frozen=True, slots=True)
class RevisionVector:
    source_context_revision: int
    goal_revision: int | None = None
    attention_revision: int | None = None

    def __post_init__(self) -> None:
        require_non_negative("source_context_revision", self.source_context_revision)
        if self.goal_revision is not None:
            require_non_negative("goal_revision", self.goal_revision)
        if self.attention_revision is not None:
            require_non_negative("attention_revision", self.attention_revision)

    def revision_for(self, kind: RevisionKind) -> int | None:
        if kind is RevisionKind.SOURCE_CONTEXT:
            return self.source_context_revision
        if kind is RevisionKind.GOAL:
            return self.goal_revision
        return self.attention_revision

    def to_dict(self) -> dict[str, object]:
        return {
            "source_context_revision": self.source_context_revision,
            "goal_revision": self.goal_revision,
            "attention_revision": self.attention_revision,
        }


@dataclass(frozen=True, slots=True)
class AuthorityRef:
    owner: str
    scope: str

    def __post_init__(self) -> None:
        require_non_empty("owner", self.owner)
        require_non_empty("scope", self.scope)

    def to_dict(self) -> dict[str, str]:
        return {"owner": self.owner, "scope": self.scope}


@dataclass(frozen=True, slots=True)
class PreconditionRef:
    precondition_id: str
    predicate: str
    subject_ref: str
    expected: JsonInput = None

    def __post_init__(self) -> None:
        require_non_empty("precondition_id", self.precondition_id)
        require_non_empty("predicate", self.predicate)
        require_non_empty("subject_ref", self.subject_ref)
        object.__setattr__(self, "expected", freeze_json(self.expected))

    def to_dict(self) -> dict[str, object]:
        return {
            "precondition_id": self.precondition_id,
            "predicate": self.predicate,
            "subject_ref": self.subject_ref,
            "expected": jsonable(cast(JsonValue, self.expected)),
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
    intent_id: str
    kind: IntentKind

    def __post_init__(self) -> None:
        require_non_empty("intent_id", self.intent_id)

    def to_dict(self) -> dict[str, str]:
        return {"intent_id": self.intent_id, "kind": self.kind.value}
