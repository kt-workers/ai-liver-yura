"""Deprecated one-way view from legacy Core config to Streaming config."""

from __future__ import annotations

from app.config.app_config import AppConfig
from app.config.service_schema import (
    DisabledServiceSettings,
    FakeObsServiceSettings,
    FakeYouTubeServiceSettings,
    ObsWebSocketServiceSettings,
    YouTubeServiceSettings,
)
from subsystems.streaming.config import (
    STREAMING_OBS_PASSWORD,
    ObsAdapterMode,
    ObsSubsystemConfig,
    StreamingSubsystemConfig,
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)


def streaming_subsystem_config_from_app_config(
    config: AppConfig,
) -> StreamingSubsystemConfig:
    """Convert legacy Core settings without resolving or retaining secret values."""

    youtube_service = config.services.get("youtube")
    if isinstance(youtube_service, YouTubeServiceSettings):
        youtube_mode = YouTubeAdapterMode.GOOGLE
    elif isinstance(youtube_service, FakeYouTubeServiceSettings):
        youtube_mode = YouTubeAdapterMode.FAKE
    elif isinstance(youtube_service, DisabledServiceSettings):
        youtube_mode = YouTubeAdapterMode.DISABLED
    else:
        raise ValueError("legacy youtube service is unsupported")

    if isinstance(youtube_service, (YouTubeServiceSettings, FakeYouTubeServiceSettings)):
        youtube = YouTubeSubsystemConfig(
            mode=youtube_mode,
            client_secret_path_ref=youtube_service.client_secret_path_env,
            token_path_ref=youtube_service.token_path_env,
            request_timeout_seconds=youtube_service.request_timeout_seconds,
            max_retries=youtube_service.max_retries,
            retry_initial_delay_seconds=youtube_service.retry_initial_delay_seconds,
            oauth_open_browser=youtube_service.oauth_open_browser,
            oauth_timeout_seconds=youtube_service.oauth_timeout_seconds,
            allow_live_broadcast=youtube_service.allow_live_broadcast,
            allowed_privacy_statuses=youtube_service.allowed_privacy_statuses,
        )
    else:
        youtube = YouTubeSubsystemConfig(mode=youtube_mode)

    obs_service = config.services.get("obs")
    if isinstance(obs_service, ObsWebSocketServiceSettings):
        obs_mode = ObsAdapterMode.OBS_WEBSOCKET
    elif isinstance(obs_service, FakeObsServiceSettings):
        obs_mode = ObsAdapterMode.FAKE
    elif isinstance(obs_service, DisabledServiceSettings):
        obs_mode = ObsAdapterMode.DISABLED
    else:
        raise ValueError("legacy OBS service is unsupported")

    legacy_obs = config.streaming.obs
    obs = ObsSubsystemConfig(
        mode=obs_mode,
        host=(
            obs_service.host
            if isinstance(obs_service, ObsWebSocketServiceSettings)
            else "127.0.0.1"
        ),
        port=(
            obs_service.port
            if isinstance(obs_service, ObsWebSocketServiceSettings)
            else 4455
        ),
        password_ref=(
            obs_service.password_env or STREAMING_OBS_PASSWORD
            if isinstance(obs_service, ObsWebSocketServiceSettings)
            else STREAMING_OBS_PASSWORD
        ),
        connect_timeout_seconds=(
            obs_service.connect_timeout_seconds
            if isinstance(obs_service, ObsWebSocketServiceSettings)
            else 5.0
        ),
        request_timeout_seconds=(
            obs_service.request_timeout_seconds
            if isinstance(obs_service, ObsWebSocketServiceSettings)
            else 5.0
        ),
        max_retries=(
            obs_service.max_retries
            if isinstance(obs_service, ObsWebSocketServiceSettings)
            else 2
        ),
        retry_initial_delay_seconds=(
            obs_service.retry_initial_delay_seconds
            if isinstance(obs_service, ObsWebSocketServiceSettings)
            else 0.5
        ),
        required_audio_sources=legacy_obs.required_audio_sources,
        optional_audio_sources=legacy_obs.optional_audio_sources,
        avatar_source_name=legacy_obs.avatar_source_name,
        low_volume_threshold_db=legacy_obs.low_volume_threshold_db,
        max_scene_depth=legacy_obs.max_scene_depth,
    )
    return StreamingSubsystemConfig(youtube=youtube, obs=obs)
