"""JSON wire codec for the versioned Streaming public contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from app.integrations.streaming.contracts import (
    StreamingCapabilities,
    StreamingCursor,
    StreamingHealth,
    StreamingIdempotencyKey,
    normalize_streaming_capabilities,
    normalize_streaming_status,
)
from app.integrations.streaming.dependency_health import (
    DependencyKind,
    StreamingDependencyHealth,
    normalize_dependency_state,
)
from app.integrations.streaming.errors import (
    StreamingError,
    normalize_streaming_error_code,
)
from app.integrations.streaming.events import (
    StreamingEventEnvelope,
    parse_streaming_event_type,
)
from app.integrations.streaming.operations import (
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingOperationType,
)
from app.integrations.streaming.versioning import StreamingApiVersion


def to_wire(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_wire(item) for item in value]
    return value


def parse_api_version(value: object) -> StreamingApiVersion:
    data = _mapping(value)
    return StreamingApiVersion(major=_integer(data, "major"), minor=_integer(data, "minor"))


def parse_health(value: object) -> StreamingHealth:
    data = _mapping(value)
    components = data.get("components", {})
    return StreamingHealth(
        status=normalize_streaming_status(_string(data, "status")),
        healthy=_boolean(data, "healthy"),
        checked_at=_datetime(data, "checked_at"),
        message=data.get("message") if isinstance(data.get("message"), str) else None,
        components={
            str(key): bool(item) for key, item in _mapping(components).items()
        },
    )


def parse_capabilities(value: object) -> StreamingCapabilities:
    data = _mapping(value)
    values = data.get("values", ())
    if not isinstance(values, list):
        raise ValueError("streaming response capabilities.values must be a list")
    return StreamingCapabilities(
        normalize_streaming_capabilities(item for item in values if isinstance(item, str))
    )


def parse_dependency(value: object) -> StreamingDependencyHealth:
    data = _mapping(value)
    capabilities = data.get("capabilities", ())
    if not isinstance(capabilities, list):
        raise ValueError("streaming dependency capabilities must be a list")
    metadata = data.get("metadata", {})
    return StreamingDependencyHealth(
        kind=DependencyKind(_string(data, "kind")),
        state=normalize_dependency_state(_string(data, "state")),
        healthy=_boolean(data, "healthy"),
        available=_boolean(data, "available"),
        checked_at=_datetime(data, "checked_at"),
        message=data.get("message") if isinstance(data.get("message"), str) else None,
        capabilities=normalize_streaming_capabilities(
            item for item in capabilities if isinstance(item, str)
        ),
        metadata=_mapping(metadata),
    )


def parse_operation_request(value: object) -> StreamingOperationRequest:
    data = _mapping(value)
    key = data.get("idempotency_key")
    payload = _mapping(data.get("payload", {}))
    return StreamingOperationRequest(
        operation_id=_string(data, "operation_id"),
        operation_type=StreamingOperationType(_string(data, "operation_type")),
        payload=payload,
        idempotency_key=(StreamingIdempotencyKey(key) if isinstance(key, str) else None),
        correlation_id=(
            data.get("correlation_id")
            if isinstance(data.get("correlation_id"), str)
            else None
        ),
    )


def parse_operation_result(value: object) -> StreamingOperationResult:
    data = _mapping(value)
    raw_error = data.get("error")
    error = None
    if isinstance(raw_error, Mapping):
        error_data = _mapping(raw_error)
        error = StreamingError(
            code=normalize_streaming_error_code(_string(error_data, "code")),
            message=_string(error_data, "message"),
            retryable=_boolean(error_data, "retryable"),
            details=_mapping(error_data.get("details", {})),
        )
    return StreamingOperationResult(
        operation_id=_string(data, "operation_id"),
        accepted=_boolean(data, "accepted"),
        status=normalize_streaming_status(_string(data, "status")),
        error=error,
        payload=_mapping(data.get("payload", {})),
    )


def parse_event(value: object) -> StreamingEventEnvelope | None:
    data = _mapping(value)
    event_type = parse_streaming_event_type(_string(data, "event_type"))
    if event_type is None:
        return None
    cursor = data.get("cursor")
    cursor_value = cursor.get("value") if isinstance(cursor, Mapping) else cursor
    return StreamingEventEnvelope(
        event_id=_string(data, "event_id"),
        event_type=event_type,
        occurred_at=_datetime(data, "occurred_at"),
        api_version=parse_api_version(data.get("api_version")),
        payload=_mapping(data.get("payload", {})),
        correlation_id=(
            data.get("correlation_id")
            if isinstance(data.get("correlation_id"), str)
            else None
        ),
        sequence=data.get("sequence") if isinstance(data.get("sequence"), int) else None,
        cursor=StreamingCursor(cursor_value) if isinstance(cursor_value, str) else None,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("streaming response must contain an object")
    return MappingProxyType({str(key): item for key, item in value.items()})


def _string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"streaming response {key} must be a string")
    return item


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"streaming response {key} must be a boolean")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"streaming response {key} must be an integer")
    return item


def _datetime(value: Mapping[str, Any], key: str) -> datetime:
    text = _string(value, key)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"streaming response {key} must include a timezone")
    return parsed
