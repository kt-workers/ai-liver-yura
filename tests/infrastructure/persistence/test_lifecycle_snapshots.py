from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

import pytest

from app.infrastructure.persistence import (
    DurabilityReceipt,
    DurabilityStatus,
    InMemoryLifecycleSnapshotRepository,
    PersistenceAvailability,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceSnapshotEnvelope,
    SnapshotPersistenceRequest,
    SnapshotPersistenceWorker,
    SqliteLifecycleSnapshotRepository,
)
from app.runtime.lifecycle import RetryPolicy

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def envelope(
    snapshot_id: str,
    revision: int,
    *,
    payload: object = {"goal": "keep"},
) -> PersistenceSnapshotEnvelope:
    return PersistenceSnapshotEnvelope(
        snapshot_id,
        "goals",
        "goal_commitment",
        "goals.commitment.snapshot.v1",
        1,
        revision,
        "runtime-1",
        NOW,
        payload,  # type: ignore[arg-type]
        source_refs=("goal-1",),
    )


def test_valid_put_get_and_newer_revision_fences_older_snapshot() -> None:
    repository = InMemoryLifecycleSnapshotRepository(lambda: NOW)
    first = repository.put_snapshot(envelope("snapshot-1", 1))
    second = repository.put_snapshot(envelope("snapshot-2", 2), expected_revision=1)
    old = repository.put_snapshot(envelope("snapshot-0", 0), expected_revision=2)

    candidate = repository.get_latest("goals", "goal_commitment")

    assert first.status is DurabilityStatus.DURABLE
    assert second.status is DurabilityStatus.DURABLE
    assert old.status is DurabilityStatus.SUPERSEDED_BY_NEWER_SNAPSHOT
    assert candidate is not None
    assert candidate.snapshot_ref == "snapshot-2"
    assert candidate.decoded_payload == {"goal": "keep"}


def test_snapshot_digest_schema_and_availability_fail_closed() -> None:
    with pytest.raises(ValueError):
        PersistenceSnapshotEnvelope(
            "snapshot-1",
            "goals",
            "goal_commitment",
            "goals.commitment.snapshot.v1",
            1,
            1,
            "runtime-1",
            NOW,
            {"goal": "keep"},
            "wrong",
        )
    repository = InMemoryLifecycleSnapshotRepository()
    repository.availability = PersistenceAvailability.UNAVAILABLE

    with pytest.raises(PersistenceError) as raised:
        repository.put_snapshot(envelope("snapshot-1", 1))

    assert raised.value.code is PersistenceFailureCode.UNAVAILABLE


def test_snapshot_worker_is_bounded_coalesced_and_shutdown_leaves_no_pending_task() -> None:
    async def run() -> None:
        repository = InMemoryLifecycleSnapshotRepository(lambda: NOW)
        worker = SnapshotPersistenceWorker(repository, max_pending=1)
        first = worker.submit(
            SnapshotPersistenceRequest("request-1", envelope("snapshot-1", 1), True)
        )
        second = worker.submit(
            SnapshotPersistenceRequest("request-2", envelope("snapshot-2", 2), True)
        )

        first_receipt = await first
        second_receipt = await second
        await worker.close()

        assert first_receipt.status is DurabilityStatus.SUPERSEDED_BY_NEWER_SNAPSHOT
        assert second_receipt.status is DurabilityStatus.DURABLE
        assert worker.pending_task_count == 0

    asyncio.run(run())


def test_non_coalescible_snapshot_requests_for_same_owner_are_each_completed() -> None:
    class DelayedRepository(InMemoryLifecycleSnapshotRepository):
        def put_snapshot(
            self,
            item: PersistenceSnapshotEnvelope,
            *,
            expected_revision: int | None = None,
        ) -> DurabilityReceipt:
            sleep(0.01)
            return super().put_snapshot(item, expected_revision=expected_revision)

    async def run() -> None:
        worker = SnapshotPersistenceWorker(DelayedRepository(lambda: NOW))
        first = worker.submit(
            SnapshotPersistenceRequest("request-1", envelope("snapshot-1", 1), False)
        )
        second = worker.submit(
            SnapshotPersistenceRequest("request-2", envelope("snapshot-2", 2), False)
        )

        first_receipt, second_receipt = await asyncio.gather(first, second)
        await worker.close()

        assert first_receipt.status is DurabilityStatus.DURABLE
        assert second_receipt.status is DurabilityStatus.DURABLE

    asyncio.run(run())


def test_sqlite_snapshot_survives_restart_without_exposing_raw_storage_shape(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "persistence.sqlite")
    initial = SqliteLifecycleSnapshotRepository(path, lambda: NOW)
    initial.put_snapshot(envelope("snapshot-1", 1))
    initial.close()

    restored = SqliteLifecycleSnapshotRepository(path, lambda: NOW)
    candidate = restored.get_latest("goals", "goal_commitment")
    restored.close()

    assert candidate is not None
    assert candidate.snapshot_ref == "snapshot-1"
    assert candidate.decoded_payload == {"goal": "keep"}


def test_sqlite_snapshot_revision_check_and_write_are_atomic(tmp_path: Path) -> None:
    repository = SqliteLifecycleSnapshotRepository(str(tmp_path / "atomic.sqlite"), lambda: NOW)

    async def write(snapshot_id: str) -> object:
        try:
            return await asyncio.to_thread(repository.put_snapshot, envelope(snapshot_id, 1))
        except PersistenceError as error:
            return error

    async def run() -> tuple[object, object]:
        values = await asyncio.gather(write("snapshot-1"), write("snapshot-2"))
        return values[0], values[1]

    first, second = asyncio.run(run())
    repository.close()

    assert sum(isinstance(value, DurabilityReceipt) for value in (first, second)) == 1
    assert sum(isinstance(value, PersistenceError) for value in (first, second)) == 1


def test_transient_failure_is_bounded_retried_without_blocking_foreground() -> None:
    class DelayedRepository(InMemoryLifecycleSnapshotRepository):
        def __init__(self) -> None:
            super().__init__(lambda: NOW)
            self.calls = 0

        def put_snapshot(
            self,
            item: PersistenceSnapshotEnvelope,
            *,
            expected_revision: int | None = None,
        ) -> DurabilityReceipt:
            self.calls += 1
            if self.calls == 1:
                sleep(0.02)
                raise PersistenceError(PersistenceFailureCode.UNAVAILABLE, "一時的に利用できません")
            return super().put_snapshot(item, expected_revision=expected_revision)

    async def run() -> None:
        repository = DelayedRepository()
        worker = SnapshotPersistenceWorker(
            repository,
            retry_policy=RetryPolicy(2, 0, 0),
        )
        receipt_task = worker.submit(
            SnapshotPersistenceRequest("request-1", envelope("snapshot-1", 1), False)
        )
        foreground_completed = False
        await asyncio.sleep(0)
        foreground_completed = True
        receipt = await receipt_task
        await worker.close()

        assert foreground_completed
        assert receipt.status is DurabilityStatus.DURABLE
        assert repository.calls == 2
        assert worker.pending_task_count == 0

    asyncio.run(run())


def test_cross_epoch_is_exposed_to_owner_as_candidate_not_applied_state() -> None:
    repository = InMemoryLifecycleSnapshotRepository(lambda: NOW)
    repository.put_snapshot(envelope("snapshot-1", 1))

    candidate = repository.get_latest("goals", "goal_commitment")

    assert candidate is not None
    assert candidate.runtime_epoch == "runtime-1"
    assert not hasattr(repository, "set_state")
    assert not hasattr(repository, "apply")


def test_newer_storage_schema_fails_closed_without_reset(tmp_path: Path) -> None:
    path = str(tmp_path / "newer.sqlite")
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE persistence_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        "INSERT INTO persistence_meta VALUES ('schema_version', '999')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(PersistenceError) as raised:
        SqliteLifecycleSnapshotRepository(path)

    assert raised.value.code is PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION


def test_compatible_migration_and_corrupt_snapshot_are_isolated(tmp_path: Path) -> None:
    path = str(tmp_path / "migration.sqlite")
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE persistence_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE lifecycle_snapshots "
        "(snapshot_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, snapshot_kind TEXT NOT NULL, "
        "owner_revision INTEGER NOT NULL, captured_at TEXT NOT NULL, envelope_json TEXT NOT NULL, "
        "obsolete INTEGER NOT NULL)"
    )
    connection.execute("INSERT INTO persistence_meta VALUES ('schema_version', '0')")
    connection.execute(
        "INSERT INTO lifecycle_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("broken-snapshot", "goals", "goal_commitment", 9, NOW.isoformat(), "{", 0),
    )
    connection.commit()
    connection.close()

    repository = SqliteLifecycleSnapshotRepository(path, lambda: NOW)
    receipt = repository.put_snapshot(envelope("snapshot-1", 1))

    assert receipt.status is DurabilityStatus.DURABLE
    assert repository.get_latest("goals", "goal_commitment") is not None
    assert repository.corrupt_snapshot_refs == ("broken-snapshot",)
    repository.close()


def test_invalid_storage_schema_version_fails_as_typed_migration_failure(tmp_path: Path) -> None:
    path = str(tmp_path / "invalid-version.sqlite")
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE persistence_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO persistence_meta VALUES ('schema_version', 'unknown')")
    connection.commit()
    connection.close()

    with pytest.raises(PersistenceError) as raised:
        SqliteLifecycleSnapshotRepository(path)

    assert raised.value.code is PersistenceFailureCode.MIGRATION_FAILED
