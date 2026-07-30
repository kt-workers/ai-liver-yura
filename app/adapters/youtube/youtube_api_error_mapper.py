"""Deprecated compatibility imports for Subsystem-owned YouTube errors."""

from subsystems.streaming.adapters.youtube.errors import (
    YouTubeApiError,
    YouTubeApiErrorKind,
    YouTubeApiErrorMapper,
    to_streaming_error,
)

__all__ = [
    "YouTubeApiError",
    "YouTubeApiErrorKind",
    "YouTubeApiErrorMapper",
    "to_streaming_error",
]
