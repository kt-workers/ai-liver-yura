"""Stable errors exposed by the Streaming public contract."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class StreamingErrorCode(str, Enum):
    """Stable error codes without external exception details."""

    UNKNOWN = "unknown"
    NOT_CONNECTED = "not_connected"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"
    EXTERNAL_DEPENDENCY_ERROR = "external_dependency_error"
    INTERNAL_ERROR = "internal_error"


def normalize_streaming_error_code(value: str) -> StreamingErrorCode:
    """Normalize an error code added by a newer producer."""

    try:
        return StreamingErrorCode(value)
    except ValueError:
        return StreamingErrorCode.UNKNOWN


@dataclass(frozen=True, slots=True)
class StreamingError:
    """A safe public error without SDK exceptions or stack traces."""

    code: StreamingErrorCode
    message: str
    retryable: bool
    details: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


class StreamingTransportError(RuntimeError):
    """Safe transport failure without leaking URLs, credentials, or SDK errors."""

    def __init__(
        self,
        code: StreamingErrorCode,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
