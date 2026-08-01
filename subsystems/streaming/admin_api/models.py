"""JSON-safe DTO helpers for the Streaming Subsystem Admin API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_PRIVATE_KEYS = frozenset(
    {
        "access_token",
        "client_secret",
        "credential",
        "live_chat_id",
        "obs_password",
        "page_token",
        "password",
        "refresh_token",
        "token",
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_json(value: object) -> Any:
    """Convert immutable contracts and Domain values without exposing private fields."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_json(getattr(value, item.name))
            for item in fields(value)
            if item.name.lower() not in _PRIVATE_KEYS
        }
    if isinstance(value, Mapping):
        return {
            str(key): to_json(item)
            for key, item in value.items()
            if str(key).lower() not in _PRIVATE_KEYS
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_json(item) for item in value]
    raise TypeError(f"admin DTO cannot serialize {type(value).__name__}")


class StreamingAdminApiError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
