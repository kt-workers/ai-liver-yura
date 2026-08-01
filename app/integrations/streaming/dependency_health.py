"""Neutral dependency health contracts for the Streaming Subsystem."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias

from app.integrations.streaming.contracts import StreamingCapability

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


class DependencyKind(str, Enum):
    TTS = "tts"
    AVATAR = "avatar"


class DependencyState(str, Enum):
    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


def normalize_dependency_state(value: str) -> DependencyState:
    """Normalize a future dependency state to a conservative fallback."""

    try:
        return DependencyState(value)
    except ValueError:
        return DependencyState.DEGRADED


@dataclass(frozen=True, slots=True)
class StreamingDependencyHealth:
    """SDK-independent health of a dependency used by Streaming."""

    kind: DependencyKind
    state: DependencyState
    healthy: bool
    available: bool
    checked_at: datetime
    message: str | None = None
    capabilities: frozenset[StreamingCapability] = frozenset()
    metadata: Mapping[str, JsonValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        if self.healthy and not self.available:
            raise ValueError("a healthy dependency must be available")
        if self.state is DependencyState.READY and not (
            self.healthy and self.available
        ):
            raise ValueError("a ready dependency must be healthy and available")
        if not self.available and self.capabilities:
            raise ValueError("an unavailable dependency cannot expose capabilities")
        expected_capability = {
            DependencyKind.TTS: StreamingCapability.TTS_AVAILABLE,
            DependencyKind.AVATAR: StreamingCapability.AVATAR_AVAILABLE,
        }[self.kind]
        if any(
            capability is not expected_capability
            for capability in self.capabilities
        ):
            raise ValueError("dependency exposes a capability for another kind")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, JsonValue]:
    return MappingProxyType(
        {
            key: _freeze_json(item, path=f"metadata.{key}")
            for key, item in value.items()
            if _require_string_key(key)
        }
    )


def _require_string_key(value: object) -> bool:
    if not isinstance(value, str):
        raise TypeError("metadata keys must be strings")
    normalized = value.lower().replace("-", "_")
    forbidden = (
        "credential",
        "cubism",
        "endpoint",
        "live2d",
        "model_path",
        "parameter_id",
        "password",
        "secret",
        "sdk",
        "speaker",
        "token",
        "voicevox",
    )
    if any(part in normalized for part in forbidden):
        raise ValueError("metadata contains an implementation-specific key")
    return True


def _freeze_json(value: object, *, path: str) -> JsonValue:
    if isinstance(value, float) and not isfinite(value):
        raise TypeError(f"{path} must contain only finite JSON numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                key: _freeze_json(item, path=f"{path}.{key}")
                for key, item in value.items()
                if _require_string_key(key)
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise TypeError(f"{path} must contain only JSON-compatible values")
