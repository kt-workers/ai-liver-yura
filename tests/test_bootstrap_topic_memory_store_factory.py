from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

from app.bootstrap import topic_memory_store_factory
from app.bootstrap.topic_memory_store_factory import (
    create_configured_topic_memory_store,
)
from app.config.app_config import load_app_config


def test_topic_memory_store_is_disabled_with_memory_setting() -> None:
    config = load_app_config()
    memory = replace(
        config.memory,
        topic_memory=replace(config.memory.topic_memory, enabled=False),
    )
    config = replace(config, memory=memory)

    assert create_configured_topic_memory_store(config) is None


def test_topic_memory_store_returns_none_without_dsn(
    monkeypatch,
) -> None:
    config = load_app_config()
    monkeypatch.delenv("AI_LIVER_DATABASE_URL", raising=False)

    assert create_configured_topic_memory_store(config) is None


def test_topic_memory_store_uses_typed_settings(monkeypatch) -> None:
    config = load_app_config()
    monkeypatch.setenv(
        "AI_LIVER_DATABASE_URL",
        "postgresql://ai_liver:password@localhost:5432/ai_liver",
    )
    created_store = object()
    constructor = Mock(return_value=created_store)
    monkeypatch.setattr(
        topic_memory_store_factory,
        "PostgresTopicMemoryStore",
        constructor,
    )

    store = create_configured_topic_memory_store(config)

    assert store is created_store
    constructor.assert_called_once()
    generated_config = constructor.call_args.args[0]
    assert generated_config.dsn == (
        "postgresql://ai_liver:password@localhost:5432/ai_liver"
    )
    assert generated_config.embedding_dimension == 1536
    assert generated_config.duplicate_threshold == (
        config.memory.topic_memory.duplicate_threshold
    )
