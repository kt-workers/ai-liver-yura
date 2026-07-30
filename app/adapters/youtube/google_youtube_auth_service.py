"""Deprecated compatibility imports for Subsystem-owned YouTube OAuth."""

from subsystems.streaming.adapters.youtube.oauth import (
    YOUTUBE_READONLY_SCOPE,
    GoogleYouTubeAuthConfig,
    GoogleYouTubeAuthService,
)

__all__ = [
    "YOUTUBE_READONLY_SCOPE",
    "GoogleYouTubeAuthConfig",
    "GoogleYouTubeAuthService",
]
