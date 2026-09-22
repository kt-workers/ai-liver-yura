"""実DBの状態保存を、競合・破損・異常終了を含めて確認する。"""

import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.infrastructure.persistence import (
    DurabilityStatus,
    PersistenceError,
    PersistenceFailureCode,
)
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase, PostgresEndpoint
from app.infrastructure.persistence.postgresql_snapshots import PostgresLifecycleSnapshotRepository
from tests.infrastructure.persistence.test_lifecycle_snapshots import envelope
from tests.infrastructure.postgresql.test_memory import POLICY


@pytest.fixture
def snapshots(
    endpoint: PostgresEndpoint,
) -> Iterator[tuple[PostgresDatabase, PostgresLifecycleSnapshotRepository]]:
    database = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repository = PostgresLifecycleSnapshotRepository(database)
        repository.migrate()
        yield database, repository
    finally:
        database.close()


def test_revision_conflict_and_rejection_never_regress_durable_revision(
    snapshots: tuple[PostgresDatabase, PostgresLifecycleSnapshotRepository],
) -> None:
    _, repository = snapshots
    assert repository.put_snapshot(envelope("first", 1)).status is DurabilityStatus.DURABLE
    assert repository.put_snapshot(envelope("second", 2), expected_revision=1).status is (
        DurabilityStatus.DURABLE
    )
    with pytest.raises(PersistenceError) as error:
        repository.put_snapshot(envelope("conflict", 3), expected_revision=1)
    assert error.value.code is PersistenceFailureCode.PERSISTENCE_CONFLICT
    repository.mark_rejected_or_obsolete("second", "所有者が復元候補を不採用にした")
    result = repository.put_snapshot(envelope("late", 0))
    assert result.status is DurabilityStatus.SUPERSEDED_BY_NEWER_SNAPSHOT
    assert result.storage_revision == 2
    assert [
        item.snapshot_ref
        for item in repository.list_compatible("goals", "goal_commitment", limit=2)
    ] == ["first"]
    with pytest.raises(PersistenceError):
        repository.put_snapshot(envelope("duplicate-revision", 2))


def test_two_initial_writers_have_only_one_durable_result(
    snapshots: tuple[PostgresDatabase, PostgresLifecycleSnapshotRepository],
) -> None:
    _, repository = snapshots

    def write(index: int) -> str:
        try:
            return repository.put_snapshot(envelope(f"snapshot-{index}", 1)).status.value
        except PersistenceError as error:
            assert error.code is PersistenceFailureCode.PERSISTENCE_CONFLICT
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(write, (1, 2)))
    assert sorted(result) == ["conflict", DurabilityStatus.DURABLE.value]
    assert len(repository.list_compatible("goals", "goal_commitment", limit=2)) == 1


@pytest.mark.parametrize(
    "field,value",
    [("payload", '{"forged":true}'), ("snapshot_id", '"different-id"'), ("payload_digest", '""')],
)
def test_tampered_payload_or_identity_is_rejected_without_rewriting(
    snapshots: tuple[PostgresDatabase, PostgresLifecycleSnapshotRepository],
    field: str,
    value: str,
) -> None:
    database, repository = snapshots
    repository.put_snapshot(envelope("first", 1))
    other = replace(envelope("unrelated", 1), owner_id="other", payload_digest="")
    repository.put_snapshot(other)
    with database.transaction() as c:
        c.execute(
            "UPDATE yura_v2.lifecycle_snapshots SET envelope_json = "
            "jsonb_set(envelope_json::jsonb, ARRAY[%s], %s::jsonb)::text "
            "WHERE snapshot_id = 'first'",
            (field, value),
        )
    with pytest.raises(PersistenceError) as error:
        repository.get_latest("goals", "goal_commitment")
    assert error.value.code is PersistenceFailureCode.INTEGRITY_FAILED
    assert repository.get_latest("other", "goal_commitment") is not None
    with database.transaction() as c:
        assert c.execute(
            "SELECT envelope_json::jsonb -> %s = %s::jsonb "
            "FROM yura_v2.lifecycle_snapshots WHERE snapshot_id = 'first'",
            (field, value),
        ).fetchone() == (True,)


def test_failed_insert_rolls_back_highest_revision(
    snapshots: tuple[PostgresDatabase, PostgresLifecycleSnapshotRepository],
) -> None:
    database, repository = snapshots
    repository.put_snapshot(envelope("first", 1))
    with pytest.raises(PersistenceError):
        repository.put_snapshot(envelope("first", 4), expected_revision=1)
    assert repository.put_snapshot(envelope("next", 2), expected_revision=1).status is (
        DurabilityStatus.DURABLE
    )
    with database.transaction() as c:
        assert c.execute("SELECT owner_revision FROM yura_v2.snapshot_heads").fetchone() == (2,)


def test_unsupported_schema_and_malformed_json_fail_without_reset(
    snapshots: tuple[PostgresDatabase, PostgresLifecycleSnapshotRepository],
) -> None:
    database, repository = snapshots
    repository.put_snapshot(envelope("first", 1))
    with database.transaction() as c:
        c.execute(
            "UPDATE yura_v2.persistence_meta SET value = '999' "
            "WHERE key = 'snapshot_schema_version'"
        )
    with pytest.raises(PersistenceError) as error:
        repository.migrate()
    assert error.value.code is PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION
    with database.transaction() as c:
        assert c.execute("SELECT count(*) FROM yura_v2.lifecycle_snapshots").fetchone() == (1,)
        c.execute("UPDATE yura_v2.lifecycle_snapshots SET envelope_json = '{'")
    with pytest.raises(PersistenceError) as error:
        repository.get_latest("goals", "goal_commitment")
    assert error.value.code is PersistenceFailureCode.CORRUPT_RECORD


def test_committed_state_survives_process_exit_without_shutdown(
    endpoint: PostgresEndpoint,
) -> None:
    script = """
import os
import sys
from app.infrastructure.persistence.postgresql_connection import (
    PostgresDatabase, PostgresEndpoint, PostgresConnectionPolicy,
)
from app.infrastructure.persistence.postgresql_snapshots import PostgresLifecycleSnapshotRepository
from tests.infrastructure.persistence.test_lifecycle_snapshots import envelope
database = PostgresDatabase.connect(
    PostgresEndpoint(sys.argv[1], int(sys.argv[3]), sys.argv[2], sys.argv[4],
                     "isolated-test-no-auth", "disable"),
    PostgresConnectionPolicy(1, 1, 1, 2, 1000, 1, 3000),
)
repository = PostgresLifecycleSnapshotRepository(database)
repository.migrate()
repository.put_snapshot(envelope("crash-committed", 7))
os._exit(29)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, endpoint.host, endpoint.database,
         str(endpoint.port), endpoint.user],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert child.returncode == 29
    database = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repository = PostgresLifecycleSnapshotRepository(database)
        repository.migrate()
        candidate = repository.get_latest("goals", "goal_commitment")
        assert candidate is not None
        assert candidate.snapshot_ref == "crash-committed"
        assert candidate.owner_state_revision == 7
        assert candidate.runtime_epoch == "runtime-1"
    finally:
        database.close()
