"""Deprecated compatibility exports for Subsystem-owned YouTube adapters."""

from subsystems.streaming.adapters.youtube.client import (
    GoogleYouTubeClientConfig,
    GoogleYouTubeClientFactory,
)
from subsystems.streaming.adapters.youtube.control import (
    GoogleYouTubeStreamingControlAdapter,
)
from subsystems.streaming.adapters.youtube.errors import (
    YouTubeApiError,
    YouTubeApiErrorKind,
    YouTubeApiErrorMapper,
)
from subsystems.streaming.adapters.youtube.google_youtube import (
    GoogleYouTubePreparationAdapter,
    GoogleYouTubePreparationConfig,
)
from subsystems.streaming.adapters.youtube.live_chat import (
    GoogleYouTubeLiveChatAdapter,
)
from subsystems.streaming.adapters.youtube.oauth import (
    GoogleYouTubeAuthConfig,
    GoogleYouTubeAuthService,
)

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
