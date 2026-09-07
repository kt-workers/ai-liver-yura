"""明示された隔離PostgreSQL上で取引・競合・接続し直しを検証する。"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import cast

import pytest

from app.domain.memory import (
    MemoryDegradationReason,
    MemoryRelation,
    MemoryRelationKind,
    MemoryStoreAuthority,
    MemoryWriteRequest,
)
from app.domain.memory.repository import MemorySemanticIndexPort
from app.infrastructure.persistence import PersistenceError, PersistenceFailureCode
from app.infrastructure.persistence.postgresql_connection import (
    PostgresConnectionPolicy,
    PostgresDatabase,
    PostgresEndpoint,
)
from app.infrastructure.persistence.postgresql_memory import PostgresMemoryRepository
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory.policy_fixtures import retrieval_policy

POLICY = PostgresConnectionPolicy(4, 4, 1, 2, 1000, 1, 3000)


@pytest.fixture
def storage(
    endpoint: PostgresEndpoint,
) -> Iterator[tuple[PostgresDatabase, PostgresMemoryRepository]]:
    database = PostgresDatabase.connect(endpoint, POLICY)
    repository = PostgresMemoryRepository(database)
    repository.migrate()
    try:
        yield database, repository
    finally:
        database.close()


def test_record_provenance_survives_new_pool(endpoint: PostgresEndpoint) -> None:
    first = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repository = PostgresMemoryRepository(first)
        repository.migrate()
        owner = MemoryStoreAuthority(repository, ranking_policy=retrieval_policy())
        result = owner.write(MemoryWriteRequest(memory.candidate()))
        assert result.record is not None
        before = repository.snapshot()
    finally:
        first.close()
    second = PostgresDatabase.connect(endpoint, POLICY)
    try:
        restored = PostgresMemoryRepository(second)
        restored.migrate()
        assert restored.snapshot() == before
        found = MemoryStoreAuthority(restored, ranking_policy=retrieval_policy()).retrieve(
            memory.query()
        )
        assert len(found.items) == 1
        assert found.items[0].provenance == result.record.provenance
    finally:
        second.close()


def test_concurrent_expected_revision_has_one_winner(
    storage: tuple[PostgresDatabase, PostgresMemoryRepository],
) -> None:
    _, repository = storage
    written = MemoryStoreAuthority(repository).write(MemoryWriteRequest(memory.candidate()))
    assert written.record is not None
    replacement = replace(written.record, revision=1)

    def write(_: int) -> bool:
        return repository.save_record(replacement, expected_revision=0)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, (1, 2)))
    assert sorted(outcomes) == [False, True]
    assert repository.get(replacement.memory_id) == replacement


def test_failed_relation_rolls_back_new_record_and_target_revision(
    storage: tuple[PostgresDatabase, PostgresMemoryRepository],
) -> None:
    _, repository = storage
    result = MemoryStoreAuthority(repository).write(MemoryWriteRequest(memory.candidate()))
    assert result.record is not None
    old = result.record
    new = replace(old, memory_id="new-record")
    relation = MemoryRelation(
        "relation",
        new.memory_id,
        "absent-record",
        MemoryRelationKind.SUPERSEDES,
        ("evidence",),
        memory.NOW,
    )
    assert not repository.commit_related(
        new, relation, target_update=replace(old, revision=1), expected_target_revision=0
    )
    assert repository.get("new-record") is None
    assert repository.get(old.memory_id) == old
    assert repository.list_relations() == ()


def test_newer_schema_is_rejected_without_erasing_records(
    storage: tuple[PostgresDatabase, PostgresMemoryRepository],
) -> None:
    database, repository = storage
    MemoryStoreAuthority(repository).write(MemoryWriteRequest(memory.candidate()))
    before = repository.snapshot()
    with database.transaction() as c:
        c.execute(
            "UPDATE yura_v2.persistence_meta SET value = '999' WHERE key = 'memory_schema_version'"
        )
    with pytest.raises(PersistenceError) as failure:
        repository.migrate()
    assert failure.value.code is PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION
    assert repository.snapshot() == before


def test_statement_timeout_is_sanitized_and_connection_is_released(
    endpoint: PostgresEndpoint,
) -> None:
    database = PostgresDatabase.connect(endpoint, replace(POLICY, statement_timeout_ms=20))
    try:
        with pytest.raises(PersistenceError) as failure:
            with database.transaction() as c:
                c.execute("SELECT pg_sleep(0.2)")
        assert failure.value.code is PersistenceFailureCode.TIMEOUT
        assert endpoint.password not in str(failure.value)
        with database.transaction() as c:
            assert c.execute("SELECT 1").fetchone() == (1,)
    finally:
        database.close()


def test_record_corruption_is_rejected_and_unrelated_record_remains_readable(
    storage: tuple[PostgresDatabase, PostgresMemoryRepository],
) -> None:
    database, repository = storage
    result = MemoryStoreAuthority(repository).write(MemoryWriteRequest(memory.candidate()))
    assert result.record is not None
    other = replace(result.record, memory_id="unrelated")
    assert repository.save_record(other, expected_revision=None)
    with database.transaction() as c:
        c.execute(
            "UPDATE yura_v2.memory_records SET payload = '{}' WHERE memory_id = %s",
            (result.record.memory_id,),
        )
    with pytest.raises(PersistenceError) as error:
        repository.get(result.record.memory_id)
    assert error.value.code is PersistenceFailureCode.INTEGRITY_FAILED
    assert repository.get(other.memory_id) == other


def test_relation_payload_must_match_database_reference_columns(
    storage: tuple[PostgresDatabase, PostgresMemoryRepository],
) -> None:
    database, repository = storage
    result = MemoryStoreAuthority(repository).write(MemoryWriteRequest(memory.candidate()))
    assert result.record is not None
    other = replace(result.record, memory_id="other")
    assert repository.save_record(other, expected_revision=None)
    relation = MemoryRelation(
        "related",
        result.record.memory_id,
        other.memory_id,
        MemoryRelationKind.SUPPORTS,
        ("evidence",),
        memory.NOW,
    )
    assert repository.save_relation(relation)
    with database.transaction() as c:
        c.execute("UPDATE yura_v2.memory_relations SET left_memory_id = %s", (other.memory_id,))
    with pytest.raises(PersistenceError) as error:
        repository.snapshot()
    assert error.value.code is PersistenceFailureCode.INTEGRITY_FAILED


def test_transaction_deadline_covers_multiple_individually_short_statements(
    endpoint: PostgresEndpoint,
) -> None:
    database = PostgresDatabase.connect(endpoint, replace(POLICY, transaction_timeout_ms=120))
    try:
        with pytest.raises(PersistenceError) as error:
            with database.transaction() as c:
                for _ in range(4):
                    c.execute("SELECT pg_sleep(0.05)")
        assert error.value.code is PersistenceFailureCode.TIMEOUT
        with database.transaction() as c:
            assert c.execute("SELECT 1").fetchone() == (1,)
    finally:
        database.close()


def test_derived_index_failure_preserves_committed_postgresql_memory(
    storage: tuple[PostgresDatabase, PostgresMemoryRepository],
) -> None:
    _, repository = storage

    class FailingIndex:
        def upsert(self, record: object) -> None:
            raise RuntimeError("試験用の派生索引を利用できません")

    owner = MemoryStoreAuthority(repository, cast(MemorySemanticIndexPort, FailingIndex()))
    result = owner.write(MemoryWriteRequest(memory.candidate()))
    assert result.record is not None
    assert result.degradation_reasons
    assert MemoryDegradationReason.REPOSITORY_UNAVAILABLE not in result.degradation_reasons
    assert repository.get(result.record.memory_id) == result.record
