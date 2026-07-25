from __future__ import annotations

from dataclasses import replace

from app.adapters.llm import DummyResponseGenerator, StreamingDemoResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.bootstrap.llm_adapter_factory import (
    create_configured_embedding_generator,
    create_configured_response_generator,
    create_configured_topic_classifier,
)
from app.bootstrap.topic_memory_store_factory import (
    create_configured_topic_memory_store,
)
from app.config.app_config import (
    AppConfig,
    LlmRoleSettings,
    ResponseGeneratorSettings,
)
from app.domain.character import CharacterProfile
from app.domain.topic_classifier import TopicClassifier
from app.ports.embedding_generator import EmbeddingGenerator
from app.ports.topic_memory_store import TopicMemoryStore


def create_response_generator(
    config: AppConfig,
    character_profile: CharacterProfile,
    prompt_builder: SimplePromptBuilder,
    *,
    temperature: float | None = None,
):
    if config.app.mode == "streaming_demo":
        return StreamingDemoResponseGenerator()
    settings = config.response_generator
    if settings.type == "dummy":
        return DummyResponseGenerator(
            character_profile=character_profile,
            prompt_builder=prompt_builder,
        )
    if settings.type != "llm":
        raise RuntimeError(
            f"未対応の response_generator.type です: {settings.type}"
        )
    return create_configured_response_generator(
        config,
        model_key=settings.model,
        fallback_response=settings.fallback_response,
        character_profile=character_profile,
        prompt_builder=prompt_builder,
        temperature=temperature,
    )


def create_llm_role_generator(
    config: AppConfig,
    settings: LlmRoleSettings,
    character_profile: CharacterProfile,
    prompt_builder: SimplePromptBuilder,
):
    role_config = replace(
        config,
        response_generator=ResponseGeneratorSettings(
            type=config.response_generator.type,
            model=settings.model,
            fallback_response=settings.fallback_response,
        ),
    )
    return create_response_generator(
        role_config,
        character_profile,
        prompt_builder,
        temperature=settings.temperature,
    )


def create_topic_classifier(config: AppConfig) -> TopicClassifier | None:
    if config.response_generator.type == "dummy":
        return None
    return create_configured_topic_classifier(
        config,
        model_key=config.topic_classifier.model,
    )


def create_embedding_generator(config: AppConfig) -> EmbeddingGenerator | None:
    topic_memory = config.memory.topic_memory
    if not topic_memory.enabled:
        return None
    return create_configured_embedding_generator(
        config,
        model_key=topic_memory.embedding_model,
    )


def create_topic_memory_store(config: AppConfig) -> TopicMemoryStore | None:
    return create_configured_topic_memory_store(config)
