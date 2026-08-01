from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.adapters.storage.postgres_topic_memory_store import (  # noqa: E402
    PostgresTopicMemoryStore,
    PostgresTopicMemoryStoreConfig,
)
from app.bootstrap.adapter_settings import (  # noqa: E402
    resolve_topic_memory_store_settings,
)
from app.config.app_config import load_app_config  # noqa: E402


async def main() -> None:
    config = load_app_config()
    topic_memory_config = config.memory.topic_memory

    if not topic_memory_config.enabled:
        print(
            "topic_memory is disabled. Set memory.topic_memory.enabled=true to initialize DB."
        )
        return

    store_settings = resolve_topic_memory_store_settings(config)
    dsn = os.environ.get(store_settings.dsn_env, "")
    if not dsn:
        raise RuntimeError(
            "database dsn is not set: " f"{store_settings.dsn_env}"
        )

    store = PostgresTopicMemoryStore(
        PostgresTopicMemoryStoreConfig(
            dsn=dsn,
            embedding_dimension=store_settings.embedding_dimension,
            duplicate_threshold=store_settings.duplicate_threshold,
            max_entries=store_settings.max_entries,
            retention_days=store_settings.retention_days,
        )
    )
    await store.initialize()
    print("topic memory database initialized.")


if __name__ == "__main__":
    asyncio.run(main())
