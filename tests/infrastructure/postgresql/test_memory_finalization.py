"""PostgreSQLの待機中も局所Memory tokenと非待機Fenceを維持する。"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.domain.contracts import SemanticSubjectIdentity, SemanticSubjectKind
from app.domain.contracts.finalization import FinalizationFailure
from app.domain.memory import (
    MemoryRelation,
    MemoryRelationKind,
    MemoryStoreAuthority,
    MemoryWriteRequest,
)
from app.infrastructure.persistence import PostgresEndpoint
from app.infrastructure.persistence.postgresql_connection import (
    PostgresConnection,
    PostgresDatabase,
)
from app.infrastructure.persistence.postgresql_memory import PostgresMemoryRepository
from tests.domain.memory.test_finalization_publication import finalize, seed
from tests.domain.memory.test_memory_store_retrieval import NOW, candidate
from tests.domain.memory.test_semantic_assertions import SEMANTICS
from tests.infrastructure.postgresql.test_memory import POLICY
from tests.infrastructure.postgresql.test_runtime import runtime


def test_same_storage_connections_share_relation_guard(endpoint: PostgresEndpoint) -> None:
    first = PostgresDatabase.connect(endpoint, POLICY)
    second = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repo = PostgresMemoryRepository(first)
        repo.migrate()
        other = PostgresMemoryRepository(second)
        store = MemoryStoreAuthority(repo)
        for mid in ("A", "B", "C"):
            seed(store, mid)
        a = store.read_semantic_assertion_publication("A", 0)
        b = store.read_semantic_assertion_publication("B", 0)
        c = store.read_semantic_assertion_publication("C", 0)
        assert other.save_relation(
            MemoryRelation("ab", "A", "B", MemoryRelationKind.CONTRADICTS, ("fact",), NOW)
        )
        record = other.get("A")
        assert record is not None and record.revision == 0
        assert finalize(a) is FinalizationFailure.GENERATION_MISMATCH
        assert finalize(b) is FinalizationFailure.GENERATION_MISMATCH
        assert finalize(c) is None
    finally:
        second.close()
        first.close()


def test_slow_postgres_write_is_busy_only_for_its_memory(endpoint: PostgresEndpoint) -> None:
    entered = Event()

    class ObservedRepository(PostgresMemoryRepository):
        def _write(self, action: Callable[[PostgresConnection], bool]) -> bool:
            # 保存入口が取得するguardだけを観測し、試験側では追加取得しない。
            entered.set()
            return super()._write(action)

    database = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repo = ObservedRepository(database)
        repo.migrate()
        store = MemoryStoreAuthority(repo)
        seed(store, "A")
        seed(store, "C")
        a = store.read_semantic_assertion_publication("A")
        c = store.read_semantic_assertion_publication("C")
        record = repo.get("A")
        assert record is not None
        entered.clear()

        def update() -> bool:
            return repo.save_record(replace(record, revision=1), expected_revision=0)

        with ThreadPoolExecutor(max_workers=1) as pool:
            with database.transaction() as connection:
                connection.execute(
                    "SELECT memory_id FROM yura_v2.memory_records WHERE memory_id='A' FOR UPDATE"
                )
                future = pool.submit(update)
                assert entered.wait(5)
                assert finalize(a) is FinalizationFailure.PARTICIPANT_BUSY
                assert finalize(c) is None
                unrelated = repo.get("C")
                assert unrelated is not None
                assert repo.save_record(replace(unrelated, revision=1), expected_revision=0)
            assert future.result(timeout=5)
        assert finalize(a) is FinalizationFailure.GENERATION_MISMATCH
    finally:
        database.close()


@pytest.mark.asyncio
async def test_runtime_publication_uses_existing_async_boundary(endpoint: PostgresEndpoint) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    try:
        absent = await binding.submit_semantic_assertion_publication("A").wait()
        assert absent.value is None and absent.failure_code is not None
        assert await persistence.start() is None
        await binding.submit_write(
            MemoryWriteRequest(
                replace(
                    candidate("A"),
                    subject_identity=SemanticSubjectIdentity(
                        SemanticSubjectKind.REFERENCE, "user:1"
                    ),
                    assertion_semantics=SEMANTICS,
                )
            )
        ).wait()
        result = await binding.submit_semantic_assertion_publication("A", 0).wait()
        assert result.value is not None and result.value.tokens
        assert finalize(result.value) is None
        await binding.submit_write(
            MemoryWriteRequest(
                replace(
                    candidate("other", source="new"),
                    subject_identity=SemanticSubjectIdentity(
                        SemanticSubjectKind.REFERENCE, "user:1"
                    ),
                    assertion_semantics=SEMANTICS,
                )
            )
        ).wait()
        assert finalize(result.value) is FinalizationFailure.GENERATION_MISMATCH
    finally:
        await binding.close()
        await persistence.close()
    assert persistence.pending_task_count == binding.pending_count == 0
