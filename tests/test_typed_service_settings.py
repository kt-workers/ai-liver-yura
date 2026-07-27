from __future__ import annotations

import pytest

from app.config.service_schema import (
    FakeYouTubeServiceSettings,
    ObsWebSocketServiceSettings,
    OpenAiServiceSettings,
    PostgresServiceSettings,
    VoiceVoxServiceSettings,
)
from app.config.typed_service_settings import (
    as_database_service,
    as_http_ai_service,
    as_obs_websocket_service,
    as_youtube_service,
)


def test_http_ai_service_requires_connection_fields() -> None:
    typed = as_http_ai_service(
        OpenAiServiceSettings(
            base_url="https://api.example.com/v1",
            api_key_env="API_KEY",
            timeout_seconds=30.0,
        ),
        service_name="openai",
        allowed_types=("openai", "ollama"),
    )

    assert typed.base_url == "https://api.example.com/v1"
    assert typed.timeout_seconds == 30.0
    assert typed.api_key_env == "API_KEY"


def test_http_ai_service_rejects_unexpected_type() -> None:
    with pytest.raises(RuntimeError, match="openai, ollama"):
        as_http_ai_service(
            VoiceVoxServiceSettings(
                base_url="http://localhost:50021",
                timeout_seconds=30.0,
            ),
            service_name="llm",
            allowed_types=("openai", "ollama"),
        )


def test_database_service_requires_postgres_dsn_environment_name() -> None:
    typed = as_database_service(
        PostgresServiceSettings(dsn_env="DATABASE_URL"),
        service_name="topic_memory_database",
    )

    assert typed.dsn_env == "DATABASE_URL"


def test_youtube_service_applies_boolean_and_privacy_defaults() -> None:
    typed = as_youtube_service(
        FakeYouTubeServiceSettings(
            client_secret_path_env="CLIENT_SECRET_PATH",
            token_path_env="TOKEN_PATH",
            request_timeout_seconds=15.0,
            max_retries=2,
            retry_initial_delay_seconds=1.0,
            oauth_open_browser=True,
            allow_live_broadcast=False,
            oauth_timeout_seconds=300.0,
            allowed_privacy_statuses=("private", "unlisted", "public"),
        )
    )

    assert typed.oauth_open_browser is True
    assert typed.allow_live_broadcast is False
    assert typed.allowed_privacy_statuses == ("private", "unlisted", "public")


def test_obs_service_rejects_invalid_port() -> None:
    with pytest.raises(RuntimeError, match="port"):
        as_obs_websocket_service(
            ObsWebSocketServiceSettings(
                host="127.0.0.1",
                port=70000,
                password_env=None,
                connect_timeout_seconds=5.0,
                request_timeout_seconds=5.0,
                max_retries=2,
                retry_initial_delay_seconds=0.5,
            )
        )
