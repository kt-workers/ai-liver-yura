"""実PostgreSQLの独立接続・行ロック・非同期受付で検索集合の現在性を検証する。"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.domain.contracts.finalization import FinalizationError, FinalizationFailure
from app.domain.memory import MemoryStoreAuthority, MemoryWriteRequest
from app.infrastructure.persistence import PostgresEndpoint
from app.infrastructure.persistence.postgresql_connection import (
    PostgresConnection,
    PostgresDatabase,
)
from app.infrastructure.persistence.postgresql_memory import PostgresMemoryRepository
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.domain.memory.test_memory_store_retrieval import candidate, query
from tests.domain.memory.test_retrieval_publication import finalized, save
from tests.infrastructure.postgresql.test_memory import POLICY
from tests.infrastructure.postgresql.test_runtime import runtime


def test_shared_connections_cover_matching_addition_and_registered_deletion(
    endpoint: PostgresEndpoint,
) -> None:
    first = PostgresDatabase.connect(endpoint, POLICY)
    second = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repo = PostgresMemoryRepository(first)
        repo.migrate()
        other = PostgresMemoryRepository(second)
        store = MemoryStoreAuthority(repo, ranking_policy=retrieval_policy())
        writer = MemoryStoreAuthority(other, ranking_policy=retrieval_policy())
        save(store, "A")
        q = query(subject_refs=("user:1",), max_estimated_tokens=10000)
        old = store.read_retrieval_publication(q)
        save(writer, "C", "other")
        assert finalized(old) is None
        save(writer, "B")
        assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
        current = store.read_retrieval_publication(q)
        assert {item.memory_id for item in current.value.items} == {"A", "B"}
        record = other.get("B")
        assert record is not None
        # 保持方針を追加せず、物理削除を行うOwnerの登録境界を検証する。
        with other.semantic_guards.mutation({"B"}):
            with other.semantic_guards.retrieval_mutation((record,)):
                with second.transaction() as connection:
                    connection.execute(
                        "DELETE FROM yura_v2.memory_records WHERE memory_id = %s", ("B",)
                    )
        assert finalized(current) is FinalizationFailure.GENERATION_MISMATCH
        assert [item.memory_id for item in store.read_retrieval_publication(q).value.items] == ["A"]
    finally:
        second.close()
        first.close()


def test_row_lock_blocks_only_matching_publication(endpoint: PostgresEndpoint) -> None:
    entered = Event()

    class ObservedRepository(PostgresMemoryRepository):
        def _write(self, action: Callable[[PostgresConnection], bool]) -> bool:
            entered.set()
            return super()._write(action)

    database = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repo = ObservedRepository(database)
        repo.migrate()
        store = MemoryStoreAuthority(repo, ranking_policy=retrieval_policy())
        save(store, "A")
        save(store, "C", "other")
        matching_query = query(subject_refs=("user:1",))
        unrelated_query = query(subject_refs=("other",))
        old = store.read_retrieval_publication(matching_query)
        unrelated = store.read_retrieval_publication(unrelated_query)
        record = repo.get("A")
        assert record is not None
        entered.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with database.transaction() as connection:
                connection.execute(
                    "SELECT memory_id FROM yura_v2.memory_records WHERE memory_id='A' FOR UPDATE"
                )
                future = pool.submit(
                    repo.save_record, replace(record, revision=1), expected_revision=0
                )
                assert entered.wait(5)
                assert finalized(old) is FinalizationFailure.PARTICIPANT_BUSY
                with pytest.raises(FinalizationError) as error:
                    store.read_retrieval_publication(matching_query)
                assert error.value.failure is FinalizationFailure.PARTICIPANT_BUSY
                assert finalized(unrelated) is None
                assert finalized(store.read_retrieval_publication(unrelated_query)) is None
                other = repo.get("C")
                assert other is not None
                assert repo.save_record(replace(other, revision=1), expected_revision=0)
            assert future.result(timeout=5)
        assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
        assert finalized(store.read_retrieval_publication(matching_query)) is None
    finally:
        database.close()


@pytest.mark.asyncio
async def test_runtime_binding_reclaims_publication_admission(endpoint: PostgresEndpoint) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    try:
        absent = await binding.read_retrieval_publication(query())
        assert absent.value is None and absent.failure_code is not None
        assert await persistence.start() is None
        await binding.submit_write(MemoryWriteRequest(candidate("A", value="A"))).wait()
        first = await binding.read_retrieval_publication(query())
        assert first.value is not None and finalized(first.value) is None
        await binding.submit_write(MemoryWriteRequest(candidate("B", value="B"))).wait()
        assert finalized(first.value) is FinalizationFailure.GENERATION_MISMATCH
        second = await binding.submit_retrieval_publication(query()).wait()
        assert second.value is not None and finalized(second.value) is None
    finally:
        await binding.close()
        await persistence.close()
    assert persistence.pending_task_count == binding.pending_count == 0


@pytest.mark.asyncio
async def test_cancelled_retrieval_waits_for_db_and_reclaims_resources(
    endpoint: PostgresEndpoint,
) -> None:
    import asyncio

    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    blocker = PostgresDatabase.connect(endpoint, POLICY)
    try:
        assert await persistence.start() is None
        with blocker.transaction() as connection:
            connection.execute("LOCK TABLE yura_v2.memory_records IN ACCESS EXCLUSIVE MODE")
            reading = asyncio.create_task(binding.read_retrieval_publication(query()))

            def waiting() -> bool:
                with blocker.transaction() as observer:
                    row = observer.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                        "AND pid <> pg_backend_pid()"
                    ).fetchone()
                    return row is not None and isinstance(row[0], int) and row[0] > 0

            async def wait_for_db() -> None:
                while not await asyncio.to_thread(waiting):
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(wait_for_db(), 2)
            reading.cancel()
            closing = asyncio.create_task(binding.close())
            await asyncio.sleep(0.02)
            assert not closing.done()
            assert persistence.pending_task_count == binding.pending_count == 1
        with pytest.raises(asyncio.CancelledError):
            await reading
        await asyncio.wait_for(closing, 2)
    finally:
        blocker.close()
        await binding.close()
        await persistence.close()
    assert persistence.pending_task_count == binding.pending_count == 0
