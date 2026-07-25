from __future__ import annotations

from dataclasses import replace

from app.adapters.storage.postgres_topic_memory_store import PostgresTopicMemoryStore
from app.bootstrap.topic_memory_store_factory import (
    create_configured_topic_memory_store,
)
from app.config.app_config import load_config


def test_topic_memory_store_is_disabled_with_memory_setting() -> None:
    config = load_config()
    memory = replace(
        config.memory,
        topic_memory=replace(config.memory.topic_memory, enabled=False),
    )
    config = replace(config, memory=memory)

    assert create_configured_topic_memory_store(config) is None


def test_topic_memory_store_returns_none_without_dsn(
    monkeypatch,
) -> None:
    config = load_config()
    monkeypatch.delenv("AI_LIVER_DATABASE_URL", raising=False)

    assert create_configured_topic_memory_store(config) is None


def test_topic_memory_store_uses_typed_settings(monkeypatch) -> None:
    config = load_config()
    monkeypatch.setenv(
        "AI_LIVER_DATABASE_URL",
        "postgresql://ai_liver:password@localhost:5432/ai_liver",
    )

    store = create_configured_topic_memory_store(config)

    assert isinstance(store, PostgresTopicMemoryStore)
