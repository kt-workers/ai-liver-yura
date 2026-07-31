"""Deprecated compatibility import.

Canonical implementation: ``subsystems.streaming.adapters.youtube``.
Removal target: phase K.
"""

import subsystems.streaming.adapters.youtube as _canonical

__getattr__ = _canonical.__getattr__

__all__ = [
    "GoogleYouTubeAuthConfig",
    "GoogleYouTubeAuthService",
    "GoogleYouTubeClientConfig",
    "GoogleYouTubeClientFactory",
    "GoogleYouTubePreparationAdapter",
    "GoogleYouTubeLiveChatAdapter",
    "GoogleYouTubePreparationConfig",
    "GoogleYouTubeStreamingControlAdapter",
    "YouTubeApiError",
    "YouTubeApiErrorKind",
    "YouTubeApiErrorMapper",
]
