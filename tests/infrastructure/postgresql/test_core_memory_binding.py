"""本体の記憶接続を、正規の振り返り結果と実PostgreSQLで検証する。"""

import asyncio

import pytest

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.domain.memory import MemoryDisposition, MemoryKind, MemoryWriteRequest, MemoryWriteResult
from app.domain.memory_reflection import (
    ReflectionAcceptancePolicy,
    ReflectionCandidateAuthority,
    ReflectionSourceKind,
)
from app.infrastructure.persistence import (
    PersistenceError,
    PersistenceFailureCode,
    PersistenceOperationResult,
    PostgresEndpoint,
    PostgresPersistenceRuntime,
    SnapshotPersistenceRetryPolicy,
)
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.domain.memory_reflection import test_memory_reflection as reflection
from tests.infrastructure.postgresql.test_memory import POLICY
from tests.infrastructure.postgresql.test_runtime import runtime


@pytest.mark.asyncio
async def test_reflection_submission_survives_runtime_restart(endpoint: PostgresEndpoint) -> None:
    context = reflection.context(
        reflection.source("execution-1", ReflectionSourceKind.EXECUTION_FACT)
    )
    accepted = ReflectionCandidateAuthority(ReflectionAcceptancePolicy("acceptance", 1)).accept(
        context, reflection.proposal("execution-1"), reflection.support("execution-1")
    )
    assert accepted.candidate is not None
    first = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(first, max_pending=2)
    try:
        assert await first.start() is None
        operation = binding.submit_reflection(accepted)
        assert operation is not None
        result = await operation.wait()
        assert result.failure_code is None and result.value is not None
        assert result.value.disposition is MemoryDisposition.STORE_NEW
        assert result.value.record is not None
        assert result.value.record.content == accepted.candidate.content
        assert accepted.candidate.provenance in result.value.record.provenance
    finally:
        await binding.close()
        await first.close()
    second = runtime(endpoint)
    reader = CoreMemoryPersistenceBinding(second, max_pending=2)
    try:
        assert await second.start() is None
        found = await reader.submit_retrieval(
            memory.query(memory_kinds=(MemoryKind.EPISODIC,))
        ).wait()
        assert found.failure_code is None and found.value is not None
        assert len(found.value.items) == 1
        assert found.value.items[0].content == accepted.candidate.content
        assert found.value.items[0].provenance == result.value.record.provenance
    finally:
        await reader.close()
        await second.close()
    assert reader.pending_count == 0
    assert second.pending_task_count == 0


@pytest.mark.asyncio
async def test_rejected_reflection_does_not_create_memory_operation(
    endpoint: PostgresEndpoint,
) -> None:
    context = reflection.context(
        reflection.source("execution-1", ReflectionSourceKind.EXECUTION_FACT)
    )
    rejected = ReflectionCandidateAuthority(ReflectionAcceptancePolicy("acceptance", 1)).accept(
        context, reflection.proposal("missing"), reflection.support("execution-1")
    )
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=1)
    try:
        assert await persistence.start() is None
        assert binding.submit_reflection(rejected) is None
        assert binding.pending_count == 0
        found = await binding.submit_retrieval(memory.query()).wait()
        assert found.value is not None and found.value.items == ()
    finally:
        await binding.close()
        await persistence.close()


@pytest.mark.asyncio
async def test_expected_revision_rejection_remains_memory_owner_decision(
    endpoint: PostgresEndpoint,
) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    try:
        assert await persistence.start() is None
        first = await binding.submit_write(MemoryWriteRequest(memory.candidate())).wait()
        assert first.value is not None and first.value.record is not None
        wrong_revision = first.value.record.revision + 1
        rejected = await binding.submit_write(
            MemoryWriteRequest(memory.candidate(), expected_revision=wrong_revision)
        ).wait()
        assert rejected.failure_code is None and rejected.value is not None
        assert rejected.value.disposition is MemoryDisposition.REJECT
        found = await binding.submit_retrieval(memory.query()).wait()
        assert found.value is not None and len(found.value.items) == 1
    finally:
        await binding.close()
        await persistence.close()


@pytest.mark.asyncio
async def test_repeated_cancel_and_close_preserve_committed_write_result(
    endpoint: PostgresEndpoint,
) -> None:
    committed = asyncio.Event()
    release = asyncio.Event()

    class DelayedRuntime(PostgresPersistenceRuntime):
        async def write_memory(
            self, request: MemoryWriteRequest
        ) -> PersistenceOperationResult[MemoryWriteResult]:
            result = await super().write_memory(request)
            committed.set()
            await release.wait()
            return result

    persistence = DelayedRuntime(
        endpoint,
        POLICY,
        retrieval_policy(),
        max_pending=2,
        snapshot_retry_policy=SnapshotPersistenceRetryPolicy(1, 0, 0),
    )
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=1)
    waiter: asyncio.Task[PersistenceOperationResult[MemoryWriteResult]] | None = None
    closer: asyncio.Task[None] | None = None
    try:
        assert await persistence.start() is None
        operation = binding.submit_write(MemoryWriteRequest(memory.candidate()))
        waiter = asyncio.create_task(operation.wait())
        await asyncio.wait_for(committed.wait(), 2)
        with pytest.raises(PersistenceError) as capacity:
            binding.submit_write(MemoryWriteRequest(memory.candidate("second")))
        assert capacity.value.code is PersistenceFailureCode.UNAVAILABLE
        waiter.cancel()
        await asyncio.sleep(0)
        waiter.cancel()
        closer = asyncio.create_task(binding.close())
        await asyncio.sleep(0)
        closer.cancel()
        await asyncio.sleep(0)
        closer.cancel()
        await asyncio.sleep(0)
        assert not waiter.done() and not closer.done()
        assert not operation.done
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiter, 2)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(closer, 2)
        result = operation.result()
        assert result.failure_code is None and result.value is not None
        assert result.value.disposition is MemoryDisposition.STORE_NEW
        assert binding.pending_count == 0
        with pytest.raises(PersistenceError) as closed:
            binding.submit_retrieval(memory.query())
        assert closed.value.code is PersistenceFailureCode.CLOSED
        found = await persistence.retrieve_memory(memory.query())
        assert found.value is not None and len(found.value.items) == 1
    finally:
        release.set()
        await asyncio.gather(
            *(task for task in (waiter, closer) if task is not None), return_exceptions=True
        )
        await binding.close()
        await persistence.close()


@pytest.mark.asyncio
async def test_unavailable_database_is_not_reported_as_written(endpoint: PostgresEndpoint) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=1)
    try:
        result = await binding.submit_write(MemoryWriteRequest(memory.candidate())).wait()
        assert result.value is None and result.failure_code is PersistenceFailureCode.UNAVAILABLE
    finally:
        await binding.close()
        await persistence.close()
