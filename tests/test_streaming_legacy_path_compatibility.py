from __future__ import annotations

import importlib

import pytest

import app.adapters.obs as legacy_obs
import app.adapters.streaming as legacy_streaming
import app.adapters.youtube as legacy_youtube
from subsystems.streaming.adapters import obs, youtube
from subsystems.streaming.adapters.obs import fake_obs
from subsystems.streaming.adapters.youtube import fake_youtube


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    (
        (legacy_youtube.GoogleYouTubeAuthService, youtube.GoogleYouTubeAuthService),
        (
            legacy_youtube.GoogleYouTubeClientFactory,
            youtube.GoogleYouTubeClientFactory,
        ),
        (
            legacy_youtube.GoogleYouTubePreparationAdapter,
            youtube.GoogleYouTubePreparationAdapter,
        ),
        (
            legacy_youtube.GoogleYouTubeLiveChatAdapter,
            youtube.GoogleYouTubeLiveChatAdapter,
        ),
        (legacy_obs.ObsWebSocketClientFactory, obs.ObsWebSocketClientFactory),
        (legacy_obs.ObsWebSocketPreparationAdapter, obs.ObsWebSocketPreparationAdapter),
        (
            legacy_obs.ObsWebSocketStreamingControlAdapter,
            obs.ObsWebSocketStreamingControlAdapter,
        ),
        (
            legacy_streaming.FakeYouTubePreparationAdapter,
            fake_youtube.FakeYouTubePreparationAdapter,
        ),
        (
            legacy_streaming.FakeObsPreparationAdapter,
            fake_obs.FakeObsPreparationAdapter,
        ),
    ),
)
def test_remaining_legacy_exports_are_identical(
    legacy: object,
    canonical: object,
) -> None:
    assert legacy is canonical


@pytest.mark.parametrize(
    "module_name",
    (
        "app.adapters.youtube.google_youtube_auth_service",
        "app.adapters.youtube.google_youtube_client_factory",
        "app.adapters.youtube.google_youtube_live_chat_adapter",
        "app.adapters.youtube.google_youtube_preparation_adapter",
        "app.adapters.youtube.google_youtube_streaming_control_adapter",
        "app.adapters.youtube.models",
        "app.adapters.youtube.youtube_api_error_mapper",
        "app.adapters.obs.models",
        "app.adapters.obs.obs_error_mapper",
        "app.adapters.obs.obs_status_mapper",
        "app.adapters.obs.obs_websocket_client_factory",
        "app.adapters.obs.obs_websocket_preparation_adapter",
        "app.adapters.obs.obs_websocket_streaming_control_adapter",
    ),
)
def test_removed_module_wrappers_are_not_importable(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
