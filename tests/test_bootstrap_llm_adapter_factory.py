from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.adapters.llm import OllamaResponseGenerator, OpenAIResponseGenerator
from app.bootstrap.llm_adapter_factory import (
    create_configured_embedding_generator,
    create_configured_response_generator,
    create_configured_topic_classifier,
)
from app.config.app_config import ServiceSettings, load_config
from app.domain.character import CharacterProfile


def character_profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="好奇心旺盛",
        speaking_style="自然体",
        streaming_style="雑談中心",
    )


def test_create_configured_response_generator_uses_openai_settings() -> None:
    config = load_config()

    generator = create_configured_response_generator(
        config,
        model_key="openai_chat",
        fallback_response="fallback",
        character_profile=character_profile(),
        prompt_builder=Mock(),
        temperature=0.4,
    )

    assert isinstance(generator, OpenAIResponseGenerator)


def test_create_configured_response_generator_uses_ollama_settings() -> None:
    config = load_config()

    generator = create_configured_response_generator(
        config,
        model_key="ollama_chat",
        fallback_response="fallback",
        character_profile=character_profile(),
        prompt_builder=Mock(),
    )

    assert isinstance(generator, OllamaResponseGenerator)


def test_openai_response_generator_requires_api_key_env() -> None:
    config = load_config()
    services = dict(config.services)
    services["openai"] = replace(services["openai"], api_key_env=None)
    config = replace(config, services=services)

    with pytest.raises(RuntimeError, match="api_key_env"):
        create_configured_response_generator(
            config,
            model_key="openai_chat",
            fallback_response="fallback",
            character_profile=character_profile(),
            prompt_builder=Mock(),
        )


def test_topic_classifier_returns_none_without_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert (
        create_configured_topic_classifier(config, model_key="openai_chat") is None
    )


def test_embedding_generator_returns_none_without_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert (
        create_configured_embedding_generator(config, model_key="openai_embedding")
        is None
    )
