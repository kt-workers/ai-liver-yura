from __future__ import annotations

from dataclasses import dataclass

from app.bootstrap.model_settings import resolve_ai_model
from app.bootstrap.service_settings import resolve_database_service
from app.config.app_config import AppConfig
from app.config.service_schema import OpenAiServiceSettings


@dataclass(frozen=True, slots=True)
class LlmAdapterSettings:
    provider: str
    model: str
    base_url: str
    timeout_seconds: float
    api_key_env: str | None


@dataclass(frozen=True, slots=True)
class TopicMemoryStoreSettings:
    dsn_env: str
    embedding_dimension: int
    duplicate_threshold: float
    max_entries: int | None
    retention_days: int | None


def resolve_llm_adapter_settings(
    config: AppConfig,
    model_key: str,
    *,
    timeout_seconds: float | None = None,
) -> LlmAdapterSettings:
    resolved = resolve_ai_model(
        config,
        model_key,
        allowed_service_types=("openai", "ollama"),
    )
    service = resolved.service
    return LlmAdapterSettings(
        provider=service.type,
        model=resolved.model.name,
        base_url=service.base_url,
        timeout_seconds=(
            timeout_seconds if timeout_seconds is not None else service.timeout_seconds
        ),
        api_key_env=(
            service.api_key_env if isinstance(service, OpenAiServiceSettings) else None
        ),
    )


def resolve_topic_memory_store_settings(
    config: AppConfig,
) -> TopicMemoryStoreSettings:
    topic_memory = config.memory.topic_memory
    database = resolve_database_service(config, topic_memory.database_service)
    embedding = resolve_ai_model(
        config,
        topic_memory.embedding_model,
        allowed_service_types=("openai",),
    )
    dimension = embedding.model.dimension
    if dimension is None:
        raise RuntimeError(
            f"models.{topic_memory.embedding_model}.dimension が必要です。"
        )
    return TopicMemoryStoreSettings(
        dsn_env=database.dsn_env,
        embedding_dimension=dimension,
        duplicate_threshold=topic_memory.duplicate_threshold,
        max_entries=topic_memory.max_entries,
        retention_days=topic_memory.retention_days,
    )
