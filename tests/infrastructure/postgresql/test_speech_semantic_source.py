"""実PostgreSQL publicationをSpeech V1へexact搬送する。"""

from dataclasses import replace

import pytest

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.composition.speech_semantics_sources import (
    ProductionSpeechSources,
    build_projection_v1,
)
from app.domain.executive.contracts import ExecutiveFactKind, ExecutiveFactRef
from app.domain.memory import MemoryWriteRequest
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from app.domain.speech_semantics.production import SpeechSemanticFactProjector
from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint
from tests.domain.memory.test_memory_store_retrieval import candidate
from tests.domain.memory.test_semantic_assertions import SEMANTICS
from tests.domain.speech_semantics.test_production_owner_sources import resolution
from tests.helpers.speech_production import IDENTITY, production_sources
from tests.infrastructure.postgresql.test_runtime import runtime


@pytest.mark.asyncio
async def test_postgres_owner_publication_to_speech(endpoint: PostgresEndpoint) -> None:
    persistence = runtime(endpoint)
    memory = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    try:
        assert await persistence.start() is None
        c = replace(
            candidate(),
            subject_identity=IDENTITY.reference_subject("user:1"),
            assertion_semantics=SEMANTICS,
        )
        result = await memory.submit_write(MemoryWriteRequest(c)).wait()
        assert result.failure_code is None and result.value is not None
        record = result.value.record
        assert record is not None
        p = production_sources()
        sources = ProductionSpeechSources(
            goals=p._goals,
            memory=memory,
            execution=p._execution,
        )
        r = await resolution(
            sources,
            ExecutiveFactRef(
                record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision, {}
            ),
        )
        binding = await sources.acquire(r)
        assert binding.tokens and all(
            t.owner_identity == "MemoryStoreAuthority" for t in binding.tokens
        )
        fact = SpeechSemanticFactProjector(build_projection_v1(IDENTITY)).project(binding)
        assert fact.subject_ref == "user:1" and fact.predicate == c.content.predicate
        assert fact.value == {
            "semantic_value": c.content.value,
            "temporal_meaning": SEMANTICS.temporal_meaning.value,
            "temporal_scope_ref": None,
            "qualifiers": (),
        }
    finally:
        await memory.close()
        await persistence.close()
    assert memory.pending_count == persistence.pending_task_count == 0


@pytest.mark.asyncio
async def test_public_memory_route_rebinds_after_restart(endpoint: PostgresEndpoint) -> None:
    p = production_sources()
    first = runtime(endpoint)
    reader = CoreMemoryPersistenceBinding(first, max_pending=2)
    try:
        assert await first.start() is None
        c = replace(
            candidate(),
            subject_identity=IDENTITY.reference_subject("user:1"),
            assertion_semantics=SEMANTICS,
        )
        written = await reader.submit_write(MemoryWriteRequest(c)).wait()
        assert written.value is not None and written.value.record is not None
        record = written.value.record
        fact = ExecutiveFactRef(
            record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision, {}
        )
        sources = ProductionSpeechSources(goals=p._goals, memory=reader, execution=p._execution)
        assert len(await sources.capture((fact,))) == 1
    finally:
        await reader.close()
        await first.close()
    second = runtime(endpoint)
    recovered = CoreMemoryPersistenceBinding(second, max_pending=2)
    try:
        assert await second.start() is None
        routes = ProductionSpeechSources(goals=p._goals, memory=recovered, execution=p._execution)
        assert await routes.capture(()) == ()
        r = await resolution(routes, fact)
        current = (await routes.acquire(r)).value
        assert isinstance(current, MemorySemanticAssertionEntry)
        assert current.assertion is not None
    finally:
        await recovered.close()
        await second.close()


@pytest.mark.asyncio
async def test_public_memory_revision_and_closed_failure(endpoint: PostgresEndpoint) -> None:
    from app.domain.speech_semantics_vocabulary import SpeechSemanticContextError
    from app.domain.speech_semantics_vocabulary import SpeechSemanticContextFailureCode as C

    p = production_sources()
    persistence = runtime(endpoint)
    memory = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    routes = ProductionSpeechSources(goals=p._goals, memory=memory, execution=p._execution)
    try:
        assert await persistence.start() is None
        c = replace(
            candidate(),
            subject_identity=IDENTITY.reference_subject("user:1"),
            assertion_semantics=SEMANTICS,
        )
        written = await memory.submit_write(MemoryWriteRequest(c)).wait()
        assert written.value is not None and written.value.record is not None
        record = written.value.record
        with pytest.raises(SpeechSemanticContextError) as error:
            await routes.capture(
                (
                    ExecutiveFactRef(
                        record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision + 1, {}
                    ),
                )
            )
        assert error.value.code is C.SOURCE_REVISION_MISMATCH
    finally:
        await memory.close()
        await persistence.close()
    with pytest.raises(SpeechSemanticContextError) as error:
        await routes.capture(
            (
                ExecutiveFactRef(
                    record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision, {}
                ),
            )
        )
    assert error.value.code is C.SOURCE_UNAVAILABLE


@pytest.mark.asyncio
async def test_source_cancel_reaps_public_memory_operation(endpoint: PostgresEndpoint) -> None:
    import asyncio

    from app.domain.contracts.finalization import AuthorityReadPublication
    from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
    from app.infrastructure.persistence import (
        PersistenceOperationResult,
        SnapshotPersistenceRetryPolicy,
    )
    from app.infrastructure.persistence.runtime import PostgresPersistenceRuntime
    from tests.domain.memory.policy_fixtures import retrieval_policy
    from tests.infrastructure.postgresql.test_memory import POLICY

    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedRuntime(PostgresPersistenceRuntime):
        async def read_memory_semantic_assertion_publication(
            self, memory_id: str, expected_revision: int | None = None
        ) -> PersistenceOperationResult[AuthorityReadPublication[MemorySemanticAssertionEntry]]:
            result = await super().read_memory_semantic_assertion_publication(
                memory_id, expected_revision
            )
            entered.set()
            await release.wait()
            return result

    persistence = DelayedRuntime(
        endpoint,
        POLICY,
        retrieval_policy(),
        max_pending=2,
        snapshot_retry_policy=SnapshotPersistenceRetryPolicy(1, 0, 0),
    )
    memory = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    p = production_sources()
    sources = ProductionSpeechSources(goals=p._goals, memory=memory, execution=p._execution)
    task = None
    try:
        assert await persistence.start() is None
        c = replace(
            candidate(),
            subject_identity=IDENTITY.reference_subject("user:1"),
            assertion_semantics=SEMANTICS,
        )
        written = await memory.submit_write(MemoryWriteRequest(c)).wait()
        assert written.value is not None and written.value.record is not None
        record = written.value.record
        task = asyncio.create_task(
            sources.capture(
                (
                    ExecutiveFactRef(
                        record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision, {}
                    ),
                )
            )
        )
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and memory.pending_count == 1
        # DB結果を取得済みでも、public operationの回収前には取消完了を名乗らない。
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert memory.pending_count == persistence.pending_task_count == 0
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await memory.close()
        await persistence.close()
    assert memory.pending_count == persistence.pending_task_count == 0
