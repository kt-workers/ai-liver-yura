"""初回の検索集合・exact-ID tokenを実DBからExecutiveの最終Fenceまで保持する。"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import pytest

from app.composition.executive import CoreExecutiveBinding, CoreExecutiveEvidence
from app.composition.executive_input_evidence import CoreExecutiveInputEvidenceReader
from app.composition.memory_evidence import (
    CoreMemoryEvidenceConfiguration,
    CoreMemoryEvidenceReader,
)
from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.domain.attention import AttentionSource
from app.domain.contracts import SemanticSubjectIdentity, SemanticSubjectKind
from app.domain.contracts.finalization import FinalizationError, FinalizationFailure
from app.domain.memory import MemoryRetrievalQuery, MemoryWriteRequest
from app.infrastructure.persistence import PersistenceError, PostgresEndpoint
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase
from app.infrastructure.persistence.postgresql_memory import PostgresMemoryRepository
from app.runtime.kernel import CancellationToken
from tests.domain.executive.test_executive import policy
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory.test_semantic_assertions import SEMANTICS
from tests.helpers.executive_requirements import make_authority
from tests.infrastructure.postgresql.test_memory import POLICY
from tests.infrastructure.postgresql.test_runtime import runtime
from tests.system_integration.test_core_input_evidence import PassivePort, wired


class RecordingReader(CoreExecutiveInputEvidenceReader):
    """本番読取の結果を記録し、二回目の読取直後へ試験の競合を挿入する。"""

    reads: list[CoreExecutiveEvidence]
    after_reread: Callable[[], Awaitable[None]] | None = None

    async def read(self, source: AttentionSource) -> CoreExecutiveEvidence:
        evidence = await super().read(source)
        self.reads.append(evidence)
        if len(self.reads) == 2 and self.after_reread is not None:
            await self.after_reread()
        return evidence


@asynccontextmanager
async def flow(endpoint: PostgresEndpoint, *, limit: int = 8) -> AsyncIterator[Any]:
    value = await wired()
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=4)
    database = PostgresDatabase.connect(endpoint, POLICY)
    port = PassivePort()
    task: asyncio.Task[Any] | None = None
    try:
        assert await persistence.start() is None
        memory_reader = CoreMemoryEvidenceReader(
            binding,
            CoreMemoryEvidenceConfiguration(
                lambda _: memory.query(
                    subject_refs=("user:1",), max_items=limit, max_estimated_tokens=100000
                ),
                limit,
                100000,
            ),
        )
        reader = RecordingReader(
            value.inputs,
            value.core.connection,
            value.registry,
            value.requirements,
            memory=memory_reader,
        )
        reader.reads = []
        authority = make_authority()
        executive = CoreExecutiveBinding(
            value.attention,
            reader,
            port,
            policy(),
            authority,
            value.core.clock,
        )
        value.memory_binding, value.persistence = binding, persistence
        value.memory_reader, value.reader = memory_reader, reader
        value.repo = PostgresMemoryRepository(database)
        value.authority, value.executive, value.port = authority, executive, port

        def begin() -> asyncio.Task[Any]:
            nonlocal task
            task = asyncio.create_task(
                executive.deliberate(
                    value.dispatch,
                    request_id="memory-current",
                    trace_id="trace",
                    decision_id="memory-current",
                    cancellation=CancellationToken(),
                )
            )
            return task

        value.begin = begin
        yield value
    finally:
        port.release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await binding.close()
        await persistence.close()
        database.close()
    assert binding.pending_count == persistence.pending_task_count == 0


async def seed(value: Any, mid: str, *, usable: bool = True, subject: str = "user:1") -> None:
    candidate = memory.candidate(mid, value=mid, subject=subject)
    if usable:
        candidate = replace(
            candidate,
            assertion_semantics=SEMANTICS,
            subject_identity=SemanticSubjectIdentity(SemanticSubjectKind.REFERENCE, subject),
        )
    result = await value.memory_binding.submit_write(MemoryWriteRequest(candidate)).wait()
    assert (
        result.failure_code is None and result.value is not None and result.value.record is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "unrelated"])
async def test_unchanged_values_accept_new_read_identity_but_fence_original_tokens(
    endpoint: PostgresEndpoint,
    change: str,
) -> None:
    async with flow(endpoint) as value:
        await seed(value, "A")
        value.port.release.clear()
        task = value.begin()
        await asyncio.wait_for(value.port.started.wait(), 2)
        if change == "unrelated":
            await seed(value, "C", subject="other")
            record = value.repo.get("C")
            assert record is not None
            assert value.repo.save_record(replace(record, revision=1), expected_revision=0)
        value.port.release.set()
        result = await asyncio.wait_for(task, 3)
        first, second = value.reader.reads
        assert first.facts == second.facts
        assert first.memory_tokens != second.memory_tokens
        assert len(first.memory_tokens) == 3
        assert {t.owner_identity for t in first.memory_tokens} == {
            "MemoryRetrievalAuthority",
            "MemoryRetrievalPolicy",
            "MemoryStoreAuthority",
        }
        assert result.evidence_tokens == first.memory_tokens
        assert value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["matching", "matching_unavailable", "empty", "available", "unavailable", "revision", "policy"],
)
async def test_mutation_during_deliberation_never_commits_old_memory(
    endpoint: PostgresEndpoint,
    change: str,
) -> None:
    async with flow(endpoint) as value:
        if change != "empty":
            await seed(value, "A", usable=change != "available")
        value.port.release.clear()
        task = value.begin()
        await asyncio.wait_for(value.port.started.wait(), 2)
        initial = value.reader.reads[0]
        if change in {"available", "empty"}:
            assert initial.facts == ()
            assert len(initial.memory_tokens) == 2
        if change in {"matching", "matching_unavailable", "empty"}:
            await seed(value, "B", usable=change == "matching")
        elif change == "policy":
            owner = value.persistence._memory
            original = owner.retrieval_ranking_policy
            owner.update_retrieval_ranking_policy(
                replace(
                    original,
                    policy_revision=original.policy_revision + 1,
                )
            )
            owner.update_retrieval_ranking_policy(original)
        else:
            record = value.repo.get("A")
            assert record is not None
            updated = replace(record, revision=1)
            if change == "available":
                updated = replace(
                    updated,
                    assertion_semantics=SEMANTICS,
                    subject_identity=SemanticSubjectIdentity(
                        SemanticSubjectKind.REFERENCE, "user:1"
                    ),
                )
            elif change == "unavailable":
                updated = replace(updated, assertion_semantics=None)
            assert value.repo.save_record(updated, expected_revision=0)
        value.port.release.set()
        if change in {"empty", "matching_unavailable", "policy"}:
            with pytest.raises(FinalizationError) as error:
                await asyncio.wait_for(task, 3)
            assert error.value.failure is FinalizationFailure.GENERATION_MISMATCH
            assert initial.facts == value.reader.reads[1].facts
        else:
            with pytest.raises(ValueError, match="根拠"):
                await asyncio.wait_for(task, 3)
        assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["matching", "exact_id"])
async def test_mutation_after_reread_is_rejected_by_final_fence(
    endpoint: PostgresEndpoint,
    change: str,
) -> None:
    async with flow(endpoint) as value:
        await seed(value, "A")

        async def mutate() -> None:
            if change == "matching":
                await seed(value, "B")
            else:
                record = value.repo.get("A")
                assert record is not None
                assert value.repo.save_record(replace(record, revision=1), expected_revision=0)

        value.reader.after_reread = mutate
        with pytest.raises(FinalizationError) as error:
            await asyncio.wait_for(value.begin(), 3)
        assert error.value.failure is FinalizationFailure.GENERATION_MISMATCH
        assert value.reader.reads[0].facts == value.reader.reads[1].facts
        assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
async def test_all_tokens_reach_existing_participant_bound(endpoint: PostgresEndpoint) -> None:
    async with flow(endpoint, limit=13) as value:
        for n in range(13):
            await seed(value, f"M{n}")
        with pytest.raises(FinalizationError) as error:
            await asyncio.wait_for(value.begin(), 3)
        assert error.value.failure is FinalizationFailure.INVALID_LOCK_CONFIGURATION
        assert len(value.reader.reads[0].facts) == 13
        assert len(value.reader.reads[0].memory_tokens) == 15
        assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
async def test_current_retrieval_without_tokens_is_not_accepted(
    endpoint: PostgresEndpoint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with flow(endpoint) as value:
        original = value.persistence.read_memory_retrieval_publication

        async def missing_tokens(query: MemoryRetrievalQuery) -> Any:
            result = await original(query)
            assert result.value is not None
            return replace(result, value=replace(result.value, tokens=()))

        monkeypatch.setattr(value.persistence, "read_memory_retrieval_publication", missing_tokens)
        with pytest.raises(ValueError, match="Owner token"):
            await value.memory_reader.read(value.dispatch.selected_source)


@pytest.mark.asyncio
async def test_storage_failure_is_not_empty_success(endpoint: PostgresEndpoint) -> None:
    async with flow(endpoint) as value:
        await value.persistence.close()
        with pytest.raises(PersistenceError):
            await value.memory_reader.read(value.dispatch.selected_source)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [False, True])
async def test_semantic_reader_preserves_adopted_index_wide_dependency(
    endpoint: PostgresEndpoint,
    mutate: bool,
) -> None:
    from app.domain.memory import MemoryStoreAuthority
    from app.domain.memory.repository import FinalizableMemorySemanticIndex
    from tests.domain.memory.test_semantic_index_synchronization import Index

    async with flow(endpoint) as value:
        await seed(value, "A")
        old_owner = value.persistence._memory
        index = FinalizableMemorySemanticIndex(Index())
        value.persistence._memory = MemoryStoreAuthority(
            value.repo,
            index,
            ranking_policy=old_owner.retrieval_ranking_policy,
        )
        index.rebuild()
        value.memory_reader.config = CoreMemoryEvidenceConfiguration(
            lambda _: memory.query(
                subject_refs=("user:1",), semantic_query="topic", max_estimated_tokens=100000
            ),
            8,
            100000,
        )
        value.port.release.clear()
        task = value.begin()
        await asyncio.wait_for(value.port.started.wait(), 2)
        initial = value.reader.reads[0]
        assert len(initial.memory_tokens) == 4
        assert "MemorySemanticIndex" in {t.owner_identity for t in initial.memory_tokens}
        if mutate:
            await seed(value, "C", subject="other")
        value.port.release.set()
        if mutate:
            with pytest.raises(FinalizationError) as error:
                await asyncio.wait_for(task, 3)
            assert error.value.failure is FinalizationFailure.GENERATION_MISMATCH
            assert initial.facts == value.reader.reads[1].facts
            assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
        else:
            result = await asyncio.wait_for(task, 3)
            assert result.evidence_tokens == initial.memory_tokens
