"""YouTube implementation bundle owned by Streaming Subsystem."""

from importlib import import_module

from subsystems.streaming.adapters.youtube.bundle import (
    YouTubeAdapterBundle,
    build_youtube_adapter_bundle,
)
from subsystems.streaming.adapters.youtube.fake_youtube import (
    FakeLiveChatAdapter,
    FakeYouTubePreparationAdapter,
    FakeYouTubePreparationConfig,
    FakeYouTubeStreamingControlAdapter,
    UnavailableYouTubePreparationAdapter,
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

_LAZY_EXPORTS = {
    "YOUTUBE_READONLY_SCOPE": "subsystems.streaming.adapters.youtube.oauth",
    "GoogleYouTubeAuthConfig": "subsystems.streaming.adapters.youtube.oauth",
    "GoogleYouTubeAuthService": "subsystems.streaming.adapters.youtube.oauth",
    "GoogleYouTubeClientConfig": "subsystems.streaming.adapters.youtube.client",
    "GoogleYouTubeClientFactory": "subsystems.streaming.adapters.youtube.client",
    "GoogleYouTubeLiveChatAdapter": ("subsystems.streaming.adapters.youtube.live_chat"),
    "GoogleYouTubePreparationAdapter": ("subsystems.streaming.adapters.youtube.google_youtube"),
    "GoogleYouTubePreparationConfig": ("subsystems.streaming.adapters.youtube.google_youtube"),
    "GoogleYouTubeStreamingControlAdapter": ("subsystems.streaming.adapters.youtube.control"),
    "YouTubeApiError": "subsystems.streaming.adapters.youtube.errors",
    "YouTubeApiErrorKind": "subsystems.streaming.adapters.youtube.errors",
    "YouTubeApiErrorMapper": "subsystems.streaming.adapters.youtube.errors",
    "to_streaming_error": "subsystems.streaming.adapters.youtube.errors",
}


def __getattr__(name: str) -> object:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name), name)
