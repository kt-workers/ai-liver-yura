from __future__ import annotations

import pytest

from app.config.app_config import _load_services
from app.config.errors import ConfigError
from app.config.service_schema import (
    DisabledServiceSettings,
    FakeObsServiceSettings,
    FakeYouTubeServiceSettings,
    ObsWebSocketServiceSettings,
    OllamaServiceSettings,
    OpenAiServiceSettings,
    PostgresServiceSettings,
    VoiceVoxServiceSettings,
    YouTubeServiceSettings,
)

YOUTUBE_FIELDS = {
    "client_secret_path_env": "YOUTUBE_CLIENT_SECRET_PATH",
    "token_path_env": "YOUTUBE_TOKEN_PATH",
    "request_timeout_seconds": 15.0,
    "max_retries": 2,
    "retry_initial_delay_seconds": 1.0,
    "oauth_open_browser": True,
    "allow_live_broadcast": False,
    "oauth_timeout_seconds": 300.0,
    "allowed_privacy_statuses": ["private", "unlisted", "public"],
}


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        (
            "openai",
            {
                "type": "openai",
                "base_url": "https://api.example.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "timeout_seconds": 30.0,
            },
            OpenAiServiceSettings,
        ),
        (
            "ollama",
            {
                "type": "ollama",
                "base_url": "http://localhost:11434",
                "timeout_seconds": 30,
            },
            OllamaServiceSettings,
        ),
        (
            "voicevox",
            {
                "type": "voicevox",
                "base_url": "http://localhost:50021",
                "timeout_seconds": 30,
            },
            VoiceVoxServiceSettings,
        ),
        (
            "database",
            {"type": "postgres", "dsn_env": "DATABASE_URL"},
            PostgresServiceSettings,
        ),
        (
            "youtube",
            {"type": "google", **YOUTUBE_FIELDS},
            YouTubeServiceSettings,
        ),
        (
            "youtube",
            {"type": "fake", **YOUTUBE_FIELDS},
            FakeYouTubeServiceSettings,
        ),
        (
            "obs",
            {
                "type": "obs_websocket",
                "host": "127.0.0.1",
                "port": 4455,
                "password_env": "OBS_PASSWORD",
                "connect_timeout_seconds": 5.0,
                "request_timeout_seconds": 5.0,
                "max_retries": 2,
                "retry_initial_delay_seconds": 0.5,
            },
            ObsWebSocketServiceSettings,
        ),
        ("obs", {"type": "fake"}, FakeObsServiceSettings),
        ("obs", {"type": "disabled"}, DisabledServiceSettings),
    ],
)
def test_service_type_is_parsed_to_its_own_schema(
    name: str, raw: dict[str, object], expected: type[object]
) -> None:
    assert isinstance(_load_services({name: raw})[name], expected)


@pytest.mark.parametrize(
    ("raw", "path"),
    [
        ({"type": "openai", "api_key_env": "KEY", "timeout_seconds": 1}, "base_url"),
        (
            {
                "type": "openai",
                "base_url": "https://example.com",
                "api_key_env": " ",
                "timeout_seconds": 1,
            },
            "api_key_env",
        ),
        (
            {
                "type": "ollama",
                "base_url": "http://localhost",
                "timeout_seconds": 0,
            },
            "timeout_seconds",
        ),
        (
            {
                "type": "ollama",
                "base_url": "http://localhost",
                "timeout_seconds": True,
            },
            "timeout_seconds",
        ),
        (
            {
                "type": "ollama",
                "base_url": "http://localhost",
                "timeout_seconds": 1,
                "api_key_env": "UNUSED",
            },
            "api_key_env",
        ),
        ({"type": "unknown"}, "type"),
    ],
)
def test_service_schema_rejects_missing_extra_unknown_and_invalid_values(
    raw: dict[str, object], path: str
) -> None:
    with pytest.raises(ConfigError, match=rf"services\.service\.{path}"):
        _load_services({"service": raw})


@pytest.mark.parametrize("port", [0, 65536, True])
def test_obs_port_is_strict_and_in_range(port: object) -> None:
    raw = {
        "type": "obs_websocket",
        "host": "127.0.0.1",
        "port": port,
        "password_env": "OBS_PASSWORD",
        "connect_timeout_seconds": 5.0,
        "request_timeout_seconds": 5.0,
        "max_retries": 2,
        "retry_initial_delay_seconds": 0.5,
    }
    with pytest.raises(ConfigError, match=r"services\.obs\.port"):
        _load_services({"obs": raw})


def test_youtube_retry_rejects_float_and_negative_values() -> None:
    with pytest.raises(ConfigError, match=r"services\.youtube\.max_retries"):
        _load_services({"youtube": {"type": "fake", **YOUTUBE_FIELDS, "max_retries": 2.5}})
    with pytest.raises(ConfigError, match=r"services\.youtube\.max_retries"):
        _load_services({"youtube": {"type": "fake", **YOUTUBE_FIELDS, "max_retries": -1}})
