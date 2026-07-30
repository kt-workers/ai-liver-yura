from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.adapters.obs import ObsWebSocketStreamingControlAdapter
from app.adapters.streaming.fake_streaming_control import (
    DisabledObsStreamingControlAdapter,
)
from app.bootstrap.streaming_runtime import create_stream_preparation_runtime
from app.config.app_config import load_app_config
from app.config.service_schema import (
    DisabledServiceSettings,
    PostgresServiceSettings,
    YouTubeServiceSettings,
)


@pytest.mark.asyncio
async def test_factory_uses_fake_services_without_real_connection() -> None:
    config = load_app_config()
    runtime = create_stream_preparation_runtime(config)
    broadcasts = await runtime.usecase.list_broadcasts()
    assert broadcasts[0].broadcast_id == config.streaming.fake.broadcast_id
    assert runtime.capability_registry.is_available("stream.session.prepare")


def test_streaming_config_keeps_secret_references_only() -> None:
    config = load_app_config()
    youtube = config.services["youtube"]
    obs = config.services["obs"]
    assert youtube.client_secret_path_env == "YOUTUBE_CLIENT_SECRET_PATH"
    assert youtube.token_path_env == "YOUTUBE_TOKEN_PATH"
    assert obs.password_env == "OBS_WEBSOCKET_PASSWORD"
    assert config.streaming.readiness.require_avatar is False


def test_default_config_path_is_independent_of_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_app_config()
    assert config.config_path.endswith("/config/index.yaml")
    assert config.services["obs"].type == "obs_websocket"


@pytest.mark.asyncio
async def test_google_factory_keeps_runtime_alive_when_env_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRET_PATH", raising=False)
    monkeypatch.delenv("YOUTUBE_TOKEN_PATH", raising=False)
    config = load_app_config()
    services = dict(config.services)
    youtube = services["youtube"]
    services["youtube"] = YouTubeServiceSettings(
        type="google",
        client_secret_path_env=youtube.client_secret_path_env,
        token_path_env=youtube.token_path_env,
        request_timeout_seconds=youtube.request_timeout_seconds,
        max_retries=youtube.max_retries,
        retry_initial_delay_seconds=youtube.retry_initial_delay_seconds,
        oauth_open_browser=youtube.oauth_open_browser,
        allow_live_broadcast=youtube.allow_live_broadcast,
        oauth_timeout_seconds=youtube.oauth_timeout_seconds,
        allowed_privacy_statuses=youtube.allowed_privacy_statuses,
    )
    runtime = create_stream_preparation_runtime(replace(config, services=services))
    state = await runtime.usecase.get_youtube_authentication_state()
    assert state.status.value == "authentication_failed"
    assert runtime.capability_registry.is_available("youtube.authentication") is False


def test_factory_selects_fake_youtube_with_real_obs_without_connecting() -> None:
    config = load_app_config()
    services = dict(config.services)

    runtime = create_stream_preparation_runtime(replace(config, services=services))

    assert runtime.usecase.youtube_adapter_type == "fake"
    assert isinstance(runtime.obs_control, ObsWebSocketStreamingControlAdapter)
    assert runtime.obs_control.adapter_type == "obs_websocket"


def test_factory_selects_disabled_obs_without_real_connection() -> None:
    config = load_app_config()
    services = dict(config.services)
    services["obs"] = DisabledServiceSettings()

    runtime = create_stream_preparation_runtime(replace(config, services=services))

    assert isinstance(runtime.obs_control, DisabledObsStreamingControlAdapter)


def test_factory_rejects_unknown_obs_type_without_fallback() -> None:
    config = load_app_config()
    services = dict(config.services)
    services["obs"] = PostgresServiceSettings(dsn_env="UNUSED_DATABASE_URL")

    with pytest.raises(RuntimeError, match="未対応のOBSサービス"):
        create_stream_preparation_runtime(replace(config, services=services))
