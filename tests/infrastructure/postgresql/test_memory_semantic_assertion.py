"""実PostgreSQLの再起動とcurrent relation更新を本体公開入口で検証する。"""

from dataclasses import replace

import pytest

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.domain.contracts import SemanticSubjectIdentity, SemanticSubjectKind
from app.domain.memory import (
    MemoryAssertionPolarity as P,
)
from app.domain.memory import (
    MemoryRelationKind,
    MemoryWriteRequest,
    project_memory_semantic_assertions,
)
from app.domain.memory import (
    MemorySemanticAssertionUnavailableReason as R,
)
from app.infrastructure.persistence import PersistenceFailureCode, PostgresEndpoint
from tests.domain.memory.test_memory_store_retrieval import candidate, query
from tests.domain.memory.test_semantic_assertions import SEMANTICS
from tests.infrastructure.postgresql.test_runtime import runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("polarity", list(P))
@pytest.mark.parametrize("subject_kind", list(SemanticSubjectKind))
async def test_roundtrip_and_current_exact_read(
    endpoint: PostgresEndpoint, polarity: P, subject_kind: SemanticSubjectKind
) -> None:
    first = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(first, max_pending=2)
    source = replace(
        candidate(),
        subject_identity=SemanticSubjectIdentity(subject_kind, "user:1"),
        assertion_semantics=replace(SEMANTICS, polarity=polarity),
    )
    try:
        assert await first.start() is None
        written = await binding.submit_write(MemoryWriteRequest(source)).wait()
        assert written.value is not None and written.value.record is not None
    finally:
        await binding.close()
        await first.close()
    second = runtime(endpoint)
    reader = CoreMemoryPersistenceBinding(second, max_pending=2)
    try:
        assert await second.start() is None
        retrieved = await reader.submit_retrieval(query()).wait()
        assert retrieved.value is not None
        evidence = retrieved.value.items[0]
        assert evidence.memory_revision == written.value.record.revision
        assert evidence.assertion_semantics == source.assertion_semantics
        assert evidence.subject_identity == source.subject_identity
        projected = project_memory_semantic_assertions(retrieved.value)
        assert projected.entries[0].assertion is not None
        assert projected.entries[0].assertion.subject_identity == source.subject_identity
        exact = await reader.submit_semantic_assertion_read(
            source.candidate_id, evidence.memory_revision
        ).wait()
        assert exact.value is not None and exact.value.assertion == projected.entries[0].assertion
        opposite = replace(
            source, candidate_id="opposite", content=replace(source.content, value="different")
        )
        await reader.submit_write(
            MemoryWriteRequest(opposite, 0, source.candidate_id, MemoryRelationKind.CONTRADICTS)
        ).wait()
        conflicted = await reader.submit_semantic_assertion_read(
            source.candidate_id, evidence.memory_revision
        ).wait()
        assert (
            conflicted.value is not None
            and conflicted.value.memory_revision == evidence.memory_revision
        )
        assert conflicted.value.unavailable_reason is R.CONFLICTED
    finally:
        await reader.close()
        await second.close()
    assert reader.pending_count == 0 and second.pending_task_count == 0
    closed = await second.read_memory_semantic_assertion(source.candidate_id)
    assert closed.failure_code is PersistenceFailureCode.CLOSED


@pytest.mark.asyncio
async def test_exact_read_unavailable_runtime_is_typed(endpoint: PostgresEndpoint) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    try:
        result = await binding.submit_semantic_assertion_read("missing", 0).wait()
        assert result.value is None and result.failure_code is PersistenceFailureCode.UNAVAILABLE
    finally:
        await binding.close()
        await persistence.close()
