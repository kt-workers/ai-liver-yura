"""本番所有者と永続化の非同期接続を、取消・停止・再起動まで検証する。"""

import asyncio
from dataclasses import replace

import pytest

from app.domain.executive import CommitmentTransitionOperation, GoalTransitionOperation
from app.domain.goals import GoalCommitmentStore
from app.domain.memory import MemoryWriteRequest
from app.infrastructure.persistence import (
    DurabilityStatus,
    PersistenceAvailability,
    PersistenceFailureCode,
    SnapshotPersistenceRetryPolicy,
)
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase, PostgresEndpoint
from app.infrastructure.persistence.runtime import PostgresPersistenceRuntime
from app.runtime.kernel import SystemRuntimeClock
from app.runtime.lifecycle import DependencyState, RuntimeLifecycle
from tests.domain.goals.test_goal_commitment_store import (
    commitment_transition,
    decision,
    goal_transition,
)
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.infrastructure.postgresql.test_memory import POLICY
from tests.runtime.test_lifecycle import retry_policy, shutdown_policy


def runtime(endpoint: PostgresEndpoint) -> PostgresPersistenceRuntime:
    return PostgresPersistenceRuntime(
        endpoint,
        POLICY,
        retrieval_policy(),
        max_pending=2,
        snapshot_retry_policy=SnapshotPersistenceRetryPolicy(1, 0, 0),
    )


def test_memory_and_owner_validated_goals_survive_runtime_restart(
    endpoint: PostgresEndpoint,
) -> None:
    async def run() -> None:
        first = runtime(endpoint)
        store = GoalCommitmentStore()
        try:
            assert await first.start() is None
            written = await first.write_memory(MemoryWriteRequest(memory.candidate()))
            assert written.failure_code is None and written.value is not None
            assert written.value.record is not None
            committed = store.apply(
                decision(
                    "create-goal-and-commitment",
                    0,
                    goals=(goal_transition(GoalTransitionOperation.CREATE, 0),),
                    commitments=(commitment_transition(CommitmentTransitionOperation.CREATE, 0),),
                )
            )
            receipt = await first.persist_goals(
                committed.snapshot, request_id="goal-save-1", runtime_epoch="before-restart"
            )
            assert receipt.status is DurabilityStatus.DURABLE
            assert receipt.owner_state_revision == committed.snapshot.revision
            assert store.snapshot() == committed.snapshot
        finally:
            await first.close()
        second = runtime(endpoint)
        try:
            assert await second.start() is None
            retrieved = await second.retrieve_memory(memory.query())
            assert retrieved.failure_code is None and retrieved.value is not None
            assert len(retrieved.value.items) == 1
            restored = await second.restore_goals()
            assert restored.failure_code is None and restored.value is not None
            assert GoalCommitmentStore(restored.value).snapshot() == committed.snapshot
        finally:
            await second.close()
        assert second.pending_task_count == 0
        assert second.availability is PersistenceAvailability.CLOSED
        assert (await second.write_memory(MemoryWriteRequest(memory.candidate()))).failure_code is (
            PersistenceFailureCode.CLOSED
        )

    asyncio.run(run())


def test_unavailable_start_is_typed_and_runtime_can_still_close(endpoint: PostgresEndpoint) -> None:
    async def run() -> None:
        service = runtime(replace(endpoint, host="/tmp/yura-missing-test-postgresql-socket"))
        try:
            failed = await service.start()
            assert failed is not None
            assert failed.failure_code == PersistenceFailureCode.CONNECTION_FAILED.value
            assert failed.retryable
            result = await service.write_memory(MemoryWriteRequest(memory.candidate()))
            assert result.value is None and result.failure_code is not None
        finally:
            await service.close()
        assert service.pending_task_count == 0

    asyncio.run(run())


def test_cancellation_and_close_wait_for_db_io_without_blocking_event_loop(
    endpoint: PostgresEndpoint,
) -> None:
    async def run() -> None:
        service = runtime(endpoint)
        assert await service.start() is None
        blocker = PostgresDatabase.connect(endpoint, POLICY)
        try:
            with blocker.transaction() as c:
                c.execute("LOCK TABLE yura_v2.memory_records IN ACCESS EXCLUSIVE MODE")
                writing = asyncio.create_task(
                    service.write_memory(MemoryWriteRequest(memory.candidate()))
                )

                def waiting() -> bool:
                    with blocker.transaction() as observer:
                        row = observer.execute(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                        ).fetchone()
                        return row is not None and isinstance(row[0], int) and row[0] > 0

                async def wait_for_db() -> None:
                    while not await asyncio.to_thread(waiting):
                        await asyncio.sleep(0.001)

                await asyncio.wait_for(wait_for_db(), 0.8)
                reading = asyncio.create_task(service.retrieve_memory(memory.query()))
                await asyncio.sleep(0)
                rejected = await service.retrieve_memory(memory.query())
                assert rejected.value is None
                assert rejected.failure_code is PersistenceFailureCode.UNAVAILABLE
                writing.cancel()
                closing = asyncio.create_task(service.close())
                await asyncio.sleep(0.02)
                assert not writing.done() and not closing.done()
                assert service.pending_task_count == 2
                closing.cancel()
                await asyncio.sleep(0)
                closing.cancel()
                await asyncio.sleep(0)
                assert not closing.done()
            with pytest.raises(asyncio.CancelledError):
                await writing
            assert (await reading).failure_code is None
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(closing, 2)
            assert service.pending_task_count == 0
            assert service.availability is PersistenceAvailability.CLOSED
        finally:
            blocker.close()
            await service.close()

    asyncio.run(run())


def test_failed_goal_persistence_never_rolls_back_current_state(endpoint: PostgresEndpoint) -> None:
    async def run() -> None:
        service = runtime(endpoint)
        try:
            assert await service.start() is None
            store = GoalCommitmentStore()
            result = store.apply(
                decision("create", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),))
            )
            assert service._database is not None
            await asyncio.to_thread(service._database.close)
            receipt = await service.persist_goals(
                result.snapshot, request_id="not-durable", runtime_epoch="test"
            )
            assert receipt.status is DurabilityStatus.FAILED
            assert receipt.failure_code is PersistenceFailureCode.CLOSED
            assert store.snapshot() == result.snapshot
        finally:
            await service.close()

    asyncio.run(run())


def test_optional_db_failure_does_not_stop_other_runtime_dependencies(
    endpoint: PostgresEndpoint,
) -> None:
    async def run() -> None:
        lifecycle = RuntimeLifecycle(SystemRuntimeClock(), shutdown_policy())
        closed: list[str] = []

        async def reconnect() -> None:
            return None

        async def close_other() -> None:
            closed.append("other")

        lifecycle.register_dependency(retry_policy("other"), reconnect=reconnect, close=close_other)
        service = runtime(replace(endpoint, host="/tmp/yura-missing-test-postgresql-socket"))
        service.attach(lifecycle, retry_policy("persistence", retry_enabled=False))
        assert await service.start() is not None
        assert lifecycle.snapshot("persistence").state is DependencyState.UNAVAILABLE
        assert lifecycle.snapshot("other").state is DependencyState.AVAILABLE
        await lifecycle.close()
        assert closed == ["other"]
        assert service.availability is PersistenceAvailability.CLOSED
        assert service.pending_task_count == 0

    asyncio.run(run())
