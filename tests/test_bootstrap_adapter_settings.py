from __future__ import annotations

from dataclasses import replace

import pytest

from app.bootstrap.adapter_settings import (
    resolve_llm_adapter_settings,
    resolve_topic_memory_store_settings,
)
from app.config.app_config import ModelSettings, load_app_config


def test_resolve_llm_adapter_settings_for_openai() -> None:
    config = load_app_config()

    settings = resolve_llm_adapter_settings(config, "openai_chat")

    assert settings.provider == "openai"
    assert settings.model == "gpt-4.1-mini"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.timeout_seconds == 60.0
    assert settings.api_key_env == "OPENAI_API_KEY"


def test_resolve_llm_adapter_settings_can_override_timeout() -> None:
    config = load_app_config()

    settings = resolve_llm_adapter_settings(
        config,
        "openai_chat",
        timeout_seconds=12.5,
    )

    assert settings.timeout_seconds == 12.5


def test_resolve_topic_memory_store_settings() -> None:
    config = load_app_config()

    settings = resolve_topic_memory_store_settings(config)

    assert settings.dsn_env == "AI_LIVER_DATABASE_URL"
    assert settings.embedding_dimension == 1536
    assert settings.duplicate_threshold == 0.95


def test_topic_memory_settings_require_embedding_dimension() -> None:
    config = load_app_config()
    model_key = config.memory.topic_memory.embedding_model
    models = dict(config.models)
    current = models[model_key]
    models[model_key] = ModelSettings(
        service=current.service,
        name=current.name,
        dimension=None,
    )

    with pytest.raises(RuntimeError, match="dimension"):
        resolve_topic_memory_store_settings(replace(config, models=models))
