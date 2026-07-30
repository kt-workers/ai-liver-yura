"""Deprecated compatibility imports for Subsystem-owned YouTube errors."""

from subsystems.streaming.adapters.youtube.errors import (
    YouTubeApiError,
    YouTubeApiErrorKind,
)

__all__ = ["YouTubeApiError", "YouTubeApiErrorKind"]
