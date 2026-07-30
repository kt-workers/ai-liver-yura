"""Deprecated compatibility imports for Subsystem-owned YouTube Adapter."""

from subsystems.streaming.adapters.youtube.google_youtube import (
    GoogleYouTubePreparationAdapter,
    GoogleYouTubePreparationConfig,
    YouTubeAuthService,
    YouTubeClientFactory,
)

__all__ = [
    "GoogleYouTubePreparationAdapter",
    "GoogleYouTubePreparationConfig",
    "YouTubeAuthService",
    "YouTubeClientFactory",
]
