from __future__ import annotations

from dataclasses import replace

import pytest

from app.bootstrap.runtime_preflight import validate_runtime_service_settings
from app.config.app_config import load_app_config


def test_validate_runtime_service_settings_accepts_default_config() -> None:
    validate_runtime_service_settings(load_app_config())


def test_validate_runtime_service_settings_skips_disabled_speech() -> None:
    config = load_app_config()
    services = dict(config.services)
    services[config.speech.service] = replace(
        services[config.speech.service],
        base_url=None,
        timeout_seconds=None,
    )
    config = replace(
        config,
        services=services,
        speech=replace(config.speech, enabled=False),
    )

    validate_runtime_service_settings(config)


def test_validate_runtime_service_settings_rejects_invalid_voicevox_config() -> None:
    config = load_app_config()
    services = dict(config.services)
    services[config.speech.service] = replace(
        services[config.speech.service],
        base_url=None,
    )
    config = replace(config, services=services)

    with pytest.raises(RuntimeError, match="services.voicevox.base_url"):
        validate_runtime_service_settings(config)


def test_validate_runtime_service_settings_rejects_invalid_topic_memory_config() -> None:
    config = load_app_config()
    models = dict(config.models)
    embedding_key = config.memory.topic_memory.embedding_model
    models[embedding_key] = replace(models[embedding_key], dimension=None)
    config = replace(config, models=models)

    with pytest.raises(RuntimeError, match=f"models.{embedding_key}.dimension"):
        validate_runtime_service_settings(config)
