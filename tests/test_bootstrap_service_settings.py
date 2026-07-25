from __future__ import annotations

from dataclasses import replace

import pytest

from app.bootstrap.service_settings import (
    resolve_database_service,
    resolve_http_ai_service,
    resolve_obs_service,
    resolve_service,
    resolve_youtube_service,
)
from app.config.app_config import load_config


def test_resolve_http_ai_service_returns_required_values() -> None:
    config = load_config()

    service = resolve_http_ai_service(config, "openai")

    assert service.type == "openai"
    assert service.base_url == "https://api.openai.com/v1"
    assert service.timeout_seconds == 60.0


def test_resolve_database_service_returns_dsn_environment_name() -> None:
    config = load_config()

    service = resolve_database_service(config, "topic_memory_database")

    assert service.type == "postgres"
    assert service.dsn_env == "AI_LIVER_DATABASE_URL"


def test_resolve_youtube_and_obs_services_use_default_names() -> None:
    config = load_config()

    youtube = resolve_youtube_service(config)
    obs = resolve_obs_service(config)

    assert youtube.type == "fake"
    assert youtube.max_retries == 2
    assert obs.type == "obs_websocket"
    assert obs.host == "127.0.0.1"
    assert obs.port == 4455


def test_resolve_service_reports_missing_name() -> None:
    config = load_config()
    config = replace(config, services={})

    with pytest.raises(RuntimeError, match="未定義のサービスです: openai"):
        resolve_service(config, "openai")
