from __future__ import annotations

import os

from app.adapters.storage.postgres_topic_memory_store import (
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.bootstrap.adapter_settings import resolve_topic_memory_store_settings
from app.config.app_config import AppConfig
from app.ports.topic_memory_store import TopicMemoryStore


def create_configured_topic_memory_store(
    config: AppConfig,
) -> TopicMemoryStore | None:
    if not config.memory.topic_memory.enabled:
        return None

    settings = resolve_topic_memory_store_settings(config)
    dsn = os.environ.get(settings.dsn_env, "")
    if not dsn:
        return None

    return PostgresTopicMemoryStore(
        PostgresTopicMemoryStoreConfig(
            dsn=dsn,
            embedding_dimension=settings.embedding_dimension,
            duplicate_threshold=settings.duplicate_threshold,
            max_entries=settings.max_entries,
            retention_days=settings.retention_days,
        )
    )
