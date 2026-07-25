from __future__ import annotations

import os

from app.adapters.embedding.openai_embedding_generator import (
    OpenAIEmbeddingGenerator,
    OpenAIEmbeddingGeneratorConfig,
)
from app.adapters.llm import OllamaResponseGenerator, OpenAIResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.adapters.topic import (
    LlmTopicClassifier,
    OllamaTopicClassificationConfig,
    OllamaTopicClassificationModel,
    OpenAITopicClassificationConfig,
    OpenAITopicClassificationModel,
)
from app.bootstrap.adapter_settings import resolve_llm_adapter_settings
from app.config.app_config import AppConfig
from app.domain.character import CharacterProfile
from app.domain.topic_classifier import TopicClassifier
from app.ports.embedding_generator import EmbeddingGenerator


def create_configured_response_generator(
    config: AppConfig,
    *,
    model_key: str,
    fallback_response: str,
    character_profile: CharacterProfile,
    prompt_builder: SimplePromptBuilder,
    temperature: float | None = None,
    timeout_seconds: float | None = None,
) -> OllamaResponseGenerator | OpenAIResponseGenerator:
    settings = resolve_llm_adapter_settings(
        config,
        model_key,
        timeout_seconds=timeout_seconds,
    )
    if settings.provider == "ollama":
        return OllamaResponseGenerator(
            character_profile=character_profile,
            prompt_builder=prompt_builder,
            model=settings.model,
            api_url=f"{settings.base_url.rstrip('/')}/api/generate",
            timeout_seconds=settings.timeout_seconds,
            fallback_response=fallback_response,
            temperature=temperature,
        )
    if settings.provider == "openai":
        if settings.api_key_env is None or not settings.api_key_env.strip():
            raise RuntimeError(
                f"models.{model_key}が参照するOpenAIサービスにはapi_key_envが必要です。"
            )
        return OpenAIResponseGenerator(
            model=settings.model,
            api_key_env=settings.api_key_env,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            fallback_response=fallback_response,
            character_profile=character_profile,
            prompt_builder=prompt_builder,
            temperature=temperature,
        )
    raise RuntimeError(f"未対応のモデルサービスです: {settings.provider}")


def create_configured_topic_classifier(
    config: AppConfig,
    *,
    model_key: str,
) -> TopicClassifier | None:
    settings = resolve_llm_adapter_settings(config, model_key)
    if settings.provider == "ollama":
        return LlmTopicClassifier(
            model=OllamaTopicClassificationModel(
                OllamaTopicClassificationConfig(
                    model=settings.model,
                    base_url=settings.base_url,
                    timeout_seconds=settings.timeout_seconds,
                )
            )
        )
    if settings.provider == "openai":
        if settings.api_key_env is None or not settings.api_key_env.strip():
            raise RuntimeError(
                f"models.{model_key}が参照するOpenAIサービスにはapi_key_envが必要です。"
            )
        api_key = os.environ.get(settings.api_key_env, "")
        if not api_key:
            return None
        return LlmTopicClassifier(
            model=OpenAITopicClassificationModel(
                OpenAITopicClassificationConfig(
                    api_key=api_key,
                    model=settings.model,
                    base_url=settings.base_url,
                    timeout_seconds=settings.timeout_seconds,
                )
            )
        )
    return None


def create_configured_embedding_generator(
    config: AppConfig,
    *,
    model_key: str,
) -> EmbeddingGenerator | None:
    settings = resolve_llm_adapter_settings(config, model_key)
    if settings.provider != "openai":
        return None
    if settings.api_key_env is None or not settings.api_key_env.strip():
        raise RuntimeError(
            f"models.{model_key}が参照するOpenAIサービスにはapi_key_envが必要です。"
        )
    api_key = os.environ.get(settings.api_key_env, "")
    if not api_key:
        return None
    return OpenAIEmbeddingGenerator(
        OpenAIEmbeddingGeneratorConfig(
            api_key=api_key,
            model=settings.model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
        )
    )
