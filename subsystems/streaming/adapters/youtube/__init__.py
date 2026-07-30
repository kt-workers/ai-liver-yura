"""YouTube implementation bundle owned by Streaming Subsystem."""

from subsystems.streaming.adapters.youtube.bundle import (
    YouTubeAdapterBundle,
    build_youtube_adapter_bundle,
)
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
    to_streaming_error,
)
from subsystems.streaming.adapters.youtube.fake_youtube import (
    FakeLiveChatAdapter,
    FakeYouTubePreparationAdapter,
    FakeYouTubePreparationConfig,
    FakeYouTubeStreamingControlAdapter,
    UnavailableYouTubePreparationAdapter,
)
from subsystems.streaming.adapters.youtube.google_youtube import (
    GoogleYouTubePreparationAdapter,
    GoogleYouTubePreparationConfig,
)
from subsystems.streaming.adapters.youtube.live_chat import (
    GoogleYouTubeLiveChatAdapter,
)
from subsystems.streaming.adapters.youtube.oauth import (
    YOUTUBE_READONLY_SCOPE,
    GoogleYouTubeAuthConfig,
    GoogleYouTubeAuthService,
)

__all__ = [
    "YOUTUBE_READONLY_SCOPE",
    "FakeLiveChatAdapter",
    "FakeYouTubePreparationAdapter",
    "FakeYouTubePreparationConfig",
    "FakeYouTubeStreamingControlAdapter",
    "GoogleYouTubeAuthConfig",
    "GoogleYouTubeAuthService",
    "GoogleYouTubeClientConfig",
    "GoogleYouTubeClientFactory",
    "GoogleYouTubeLiveChatAdapter",
    "GoogleYouTubePreparationAdapter",
    "GoogleYouTubePreparationConfig",
    "GoogleYouTubeStreamingControlAdapter",
    "UnavailableYouTubePreparationAdapter",
    "YouTubeAdapterBundle",
    "YouTubeApiError",
    "YouTubeApiErrorKind",
    "YouTubeApiErrorMapper",
    "build_youtube_adapter_bundle",
    "to_streaming_error",
]
