from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import init_topic_memory_db


@pytest.mark.asyncio
async def test_main_uses_current_topic_memory_store_settings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = SimpleNamespace(
        memory=SimpleNamespace(
            topic_memory=SimpleNamespace(enabled=True),
        )
    )
    store_settings = SimpleNamespace(
        dsn_env="TEST_TOPIC_MEMORY_DSN",
        embedding_dimension=1536,
        duplicate_threshold=0.91,
        max_entries=250,
        retention_days=30,
    )
    captured = SimpleNamespace(config=None, initialized=False)

    class RecordingStore:
        def __init__(self, store_config: object) -> None:
            captured.config = store_config

        async def initialize(self) -> None:
            captured.initialized = True

    monkeypatch.setattr(init_topic_memory_db, "load_app_config", lambda: config)
    monkeypatch.setattr(
        init_topic_memory_db,
        "resolve_topic_memory_store_settings",
        lambda actual_config: store_settings,
    )
    monkeypatch.setattr(init_topic_memory_db, "PostgresTopicMemoryStore", RecordingStore)
    monkeypatch.setenv(
        "TEST_TOPIC_MEMORY_DSN",
        "postgresql://ai_liver:password@127.0.0.1:5432/ai_liver",
    )

    await init_topic_memory_db.main()

    assert captured.initialized is True
    assert captured.config.dsn == (
        "postgresql://ai_liver:password@127.0.0.1:5432/ai_liver"
    )
    assert captured.config.embedding_dimension == 1536
    assert captured.config.duplicate_threshold == 0.91
    assert captured.config.max_entries == 250
    assert captured.config.retention_days == 30
    assert capsys.readouterr().out == "topic memory database initialized.\n"


@pytest.mark.asyncio
async def test_main_reports_resolved_dsn_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        memory=SimpleNamespace(
            topic_memory=SimpleNamespace(enabled=True),
        )
    )
    store_settings = SimpleNamespace(
        dsn_env="MISSING_TOPIC_MEMORY_DSN",
        embedding_dimension=1536,
        duplicate_threshold=0.95,
        max_entries=None,
        retention_days=None,
    )

    monkeypatch.setattr(init_topic_memory_db, "load_app_config", lambda: config)
    monkeypatch.setattr(
        init_topic_memory_db,
        "resolve_topic_memory_store_settings",
        lambda actual_config: store_settings,
    )
    monkeypatch.delenv("MISSING_TOPIC_MEMORY_DSN", raising=False)

    with pytest.raises(
        RuntimeError,
        match="database dsn is not set: MISSING_TOPIC_MEMORY_DSN",
    ):
        await init_topic_memory_db.main()


@pytest.mark.asyncio
async def test_main_skips_resolution_when_topic_memory_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = SimpleNamespace(
        memory=SimpleNamespace(
            topic_memory=SimpleNamespace(enabled=False),
        )
    )

    def fail_if_called(actual_config: object) -> None:
        raise AssertionError("settings resolver must not be called")

    monkeypatch.setattr(init_topic_memory_db, "load_app_config", lambda: config)
    monkeypatch.setattr(
        init_topic_memory_db,
        "resolve_topic_memory_store_settings",
        fail_if_called,
    )

    await init_topic_memory_db.main()

    assert capsys.readouterr().out == (
        "topic_memory is disabled. "
        "Set memory.topic_memory.enabled=true to initialize DB.\n"
    )
