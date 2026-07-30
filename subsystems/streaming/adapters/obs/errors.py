from __future__ import annotations

from dataclasses import dataclass

from app.integrations.streaming import StreamingError, StreamingErrorCode


@dataclass(frozen=True, slots=True)
class ObsAdapterError(RuntimeError):
    category: str
    failure_code: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.failure_code


class ObsErrorMapper:
    @staticmethod
    def map(error: Exception) -> ObsAdapterError:
        name = type(error).__name__.lower()
        message = str(error).lower()
        if isinstance(error, ObsAdapterError):
            return error
        if (
            "auth" in message
            or "password" in message
            or "failed to identify client" in message
        ):
            return ObsAdapterError("authentication", "obs.authentication_failed")
        if "timeout" in name or "timeout" in message:
            return ObsAdapterError("timeout", "obs.request_timeout", True)
        if isinstance(error, ConnectionRefusedError) or "refused" in message:
            return ObsAdapterError("connection_refused", "obs.connection_refused", True)
        if "request" in name and "not found" in message:
            return ObsAdapterError("not_found", "obs.source_not_found")
        if "request" in name:
            return ObsAdapterError("request_failed", "obs.request_failed")
        if isinstance(error, (ConnectionError, OSError)):
            return ObsAdapterError("network", "obs.network_error", True)
        return ObsAdapterError("unknown", "obs.unknown_error")


def to_streaming_error(error: Exception) -> StreamingError:
    """Map OBS and transport failures to the stable public contract."""

    mapped = ObsErrorMapper.map(error)
    code = {
        "authentication": StreamingErrorCode.UNAVAILABLE,
        "configuration": StreamingErrorCode.UNAVAILABLE,
        "connection_refused": StreamingErrorCode.UNAVAILABLE,
        "network": StreamingErrorCode.UNAVAILABLE,
        "timeout": StreamingErrorCode.TIMEOUT,
        "start_rejected": StreamingErrorCode.CONFLICT,
        "stop_rejected": StreamingErrorCode.CONFLICT,
        "unsupported_operation": StreamingErrorCode.UNSUPPORTED_OPERATION,
    }.get(mapped.category, StreamingErrorCode.EXTERNAL_DEPENDENCY_ERROR)
    return StreamingError(
        code=code,
        message=mapped.failure_code,
        retryable=mapped.retryable,
    )
