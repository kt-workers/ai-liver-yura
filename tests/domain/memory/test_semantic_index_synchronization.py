"""派生indexの全体依存と、正本との同期失敗を現在公開へ隠さない。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from app.domain.contracts.finalization import FinalizationError, FinalizationFailure
from app.domain.memory import (
    MemoryDegradationReason,
    MemoryDisposition,
    MemoryRecord,
    MemoryRelation,
    MemoryRelationKind,
    MemoryStoreAuthority,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from app.domain.memory.ranking import MemorySemanticRelevance
from app.domain.memory.repository import (
    FinalizableMemorySemanticIndex,
    InMemoryMemoryRepository,
    MemorySemanticIndexState,
)
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.domain.memory.test_memory_store_retrieval import candidate, query
from tests.domain.memory.test_retrieval_publication import finalized, save


class Index:
    def __init__(self) -> None:
        self.records: dict[str, MemoryRecord] = {}
        self.fail = False
        self.entered = Event()
        self.release = Event()
        self.slow = False
        self.blocked_id: str | None = None

    def rebuild(self, records: tuple[MemoryRecord, ...]) -> None:
        self.records = {record.memory_id: record for record in records}

    def upsert(self, record: MemoryRecord) -> None:
        if self.fail:
            raise RuntimeError("試験用のindex更新失敗")
        if self.slow and (self.blocked_id is None or self.blocked_id == record.memory_id):
            self.entered.set()
            assert self.release.wait(5)
        self.records[record.memory_id] = record

    def related_scores(self, text: str, *, limit: int) -> tuple[MemorySemanticRelevance, ...]:
        # 構造filter前の全体top-Nで、範囲外の高得点候補が既存候補を押し出す。
        ids = sorted(self.records, reverse=True)[:limit]
        return tuple(MemorySemanticRelevance(mid, 1.0) for mid in ids)


def setup() -> (
    tuple[MemoryStoreAuthority, InMemoryMemoryRepository, FinalizableMemorySemanticIndex, Index]
):
    repo = InMemoryMemoryRepository()
    backend = Index()
    index = FinalizableMemorySemanticIndex(backend)
    store = MemoryStoreAuthority(repo, index, ranking_policy=retrieval_policy())
    index.rebuild()
    return store, repo, index, backend


def unavailable(store: MemoryStoreAuthority, failure: FinalizationFailure) -> None:
    with pytest.raises(FinalizationError) as error:
        store.read_retrieval_publication(query(semantic_query="topic"))
    assert error.value.failure is failure


def test_semantic_global_top_n_changes_while_structural_query_remains_current() -> None:
    store, repo, index, backend = setup()
    save(store, "A")
    q = query(subject_refs=("user:1",), semantic_query="topic", max_items=1)
    old = store.read_retrieval_publication(q)
    normal = store.read_retrieval_publication(query(subject_refs=("user:1",)))
    assert backend.related_scores("topic", limit=1)[0].memory_id == "A"
    save(store, "C", "other")
    assert index.synchronization_state is MemorySemanticIndexState.CURRENT
    assert backend.related_scores("topic", limit=1)[0].memory_id == "C"
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
    assert finalized(normal) is None
    current = store.read_retrieval_publication(q)
    assert current.value.items != old.value.items
    assert finalized(current) is None
    save(store, "B")
    assert finalized(current) is FinalizationFailure.GENERATION_MISMATCH
    assert repo.get("B") is not None


def test_failed_upsert_cannot_recover_on_successful_read_or_later_upsert() -> None:
    store, repo, index, backend = setup()
    save(store, "A")
    old = store.read_retrieval_publication(query(semantic_query="topic"))
    backend.fail = True
    result = store.write(MemoryWriteRequest(candidate("B", value="B")))
    assert result.record is not None and repo.get("B") == result.record
    assert result.degradation_reasons == (MemoryDegradationReason.SEMANTIC_INDEX_UPDATE_FAILED,)
    assert backend.related_scores("topic", limit=8)
    state_before_repair = index.synchronization_state
    assert state_before_repair is MemorySemanticIndexState.DEGRADED
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    assert store.retrieve(query(semantic_query="topic")).degraded
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
    normal = store.read_retrieval_publication(query())
    assert not normal.value.degraded and finalized(normal) is None
    backend.fail = False
    index.upsert(result.record)
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    index.rebuild()
    assert index.synchronization_state is MemorySemanticIndexState.CURRENT
    assert set(backend.records) == {"A", "B"}
    assert finalized(store.read_retrieval_publication(query(semantic_query="topic"))) is None


def test_commit_to_upsert_gap_is_degraded_and_does_not_stop_structural_reads() -> None:
    entered, release = Event(), Event()

    class PausedAuthority(MemoryStoreAuthority):
        def _indexed(
            self,
            disposition: MemoryDisposition,
            record: MemoryRecord,
            relation: MemoryRelation | None,
            related_records: tuple[MemoryRecord, ...] = (),
        ) -> MemoryWriteResult:
            entered.set()
            assert release.wait(5)
            return super()._indexed(disposition, record, relation, related_records)

    repo = InMemoryMemoryRepository()
    index = FinalizableMemorySemanticIndex(Index())
    store = PausedAuthority(repo, index, ranking_policy=retrieval_policy())
    index.rebuild()
    with ThreadPoolExecutor(max_workers=1) as pool:
        writing = pool.submit(store.write, MemoryWriteRequest(candidate("A", value="A")))
        try:
            assert entered.wait(5)
            assert repo.get("A") is not None
            assert index.synchronization_state is MemorySemanticIndexState.DEGRADED
            unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
            assert finalized(store.read_retrieval_publication(query())) is None
        finally:
            release.set()
        assert writing.result(timeout=5).record is not None
    assert finalized(store.read_retrieval_publication(query(semantic_query="topic"))) is None


def test_pending_provider_does_not_hold_global_participant_or_block_canonical_write() -> None:
    store, repo, index, backend = setup()
    save(store, "A")
    normal = store.read_retrieval_publication(query(subject_refs=("user:1",)))
    old = store.read_retrieval_publication(query(semantic_query="topic"))
    backend.slow = True
    backend.blocked_id = "C"
    with ThreadPoolExecutor(max_workers=1) as pool:
        writing = pool.submit(store.write, MemoryWriteRequest(candidate("C", subject="other")))
        try:
            assert backend.entered.wait(5)
            assert index.synchronization_state is MemorySemanticIndexState.UPDATE_PENDING
            unavailable(store, FinalizationFailure.PARTICIPANT_BUSY)
            assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
            assert finalized(normal) is None
            save(store, "D", "independent")
            assert backend.records["D"] == repo.get("D")
            assert finalized(normal) is None
            assert (
                finalized(store.read_retrieval_publication(query(subject_refs=("user:1",)))) is None
            )
            a = repo.get("A")
            assert a is not None
            assert repo.save_record(replace(a, revision=1), expected_revision=0)
        finally:
            backend.release.set()
        assert writing.result(timeout=5).record is not None
    # 別writerの未同期変更を、Cの完了で消してはならない。
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    index.rebuild()
    assert finalized(store.read_retrieval_publication(query(semantic_query="topic"))) is None


def test_supersede_synchronizes_both_records_and_relation_keeps_both_endpoints() -> None:
    store, repo, index, backend = setup()
    save(store, "A")
    old = store.read_retrieval_publication(query(semantic_query="topic"))
    result = store.write(
        MemoryWriteRequest(
            candidate("B", value="B"),
            target_memory_id="A",
            expected_revision=0,
            relation_kind=MemoryRelationKind.SUPERSEDES,
        )
    )
    assert result.record is not None and not result.degradation_reasons
    assert backend.records["A"] == repo.get("A")
    assert backend.records["B"] == repo.get("B")
    assert index.synchronization_state is MemorySemanticIndexState.CURRENT
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH


def test_registered_purge_requires_full_rebuild_to_remove_stale_index_entry() -> None:
    store, repo, index, backend = setup()
    save(store, "A")
    record = repo.get("A")
    assert record is not None
    with repo.semantic_guards.mutation({"A"}):
        with repo.semantic_guards.retrieval_mutation((record,)):
            del repo._records["A"]
    assert "A" in backend.records
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    index.rebuild()
    assert not backend.records
    assert finalized(store.read_retrieval_publication(query(semantic_query="topic"))) is None


def test_rebuild_racing_canonical_mutation_stays_degraded_until_explicit_retry() -> None:
    entered, release = Event(), Event()

    class SlowRebuild(Index):
        slow_rebuild = False

        def rebuild(self, records: tuple[MemoryRecord, ...]) -> None:
            if self.slow_rebuild:
                entered.set()
                assert release.wait(5)
            super().rebuild(records)

    repo = InMemoryMemoryRepository()
    backend = SlowRebuild()
    index = FinalizableMemorySemanticIndex(backend)
    store = MemoryStoreAuthority(repo, index, ranking_policy=retrieval_policy())
    index.rebuild()
    save(store, "A")
    backend.slow_rebuild = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        repairing = pool.submit(index.rebuild)
        try:
            assert entered.wait(5)
            unavailable(store, FinalizationFailure.PARTICIPANT_BUSY)
            result = store.write(MemoryWriteRequest(candidate("B", value="B")))
            assert result.record is not None
            assert result.degradation_reasons == (
                MemoryDegradationReason.SEMANTIC_INDEX_UPDATE_FAILED,
            )
            assert finalized(store.read_retrieval_publication(query())) is None
        finally:
            release.set()
        with pytest.raises(RuntimeError):
            repairing.result(timeout=5)
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    backend.slow_rebuild = False
    index.rebuild()
    assert set(backend.records) == {"A", "B"}
    assert finalized(store.read_retrieval_publication(query(semantic_query="topic"))) is None


def test_query_racing_upsert_does_not_capture_new_generation_for_old_scores() -> None:
    entered, release = Event(), Event()

    class SlowRead(Index):
        def related_scores(self, text: str, *, limit: int) -> tuple[MemorySemanticRelevance, ...]:
            result = super().related_scores(text, limit=limit)
            entered.set()
            assert release.wait(5)
            return result

    repo = InMemoryMemoryRepository()
    backend = SlowRead()
    index = FinalizableMemorySemanticIndex(backend)
    store = MemoryStoreAuthority(repo, index, ranking_policy=retrieval_policy())
    index.rebuild()
    save(store, "A")
    with ThreadPoolExecutor(max_workers=1) as pool:
        reading = pool.submit(
            store.read_retrieval_publication,
            query(subject_refs=("user:1",), semantic_query="topic"),
        )
        try:
            assert entered.wait(5)
            save(store, "C", "other")
        finally:
            release.set()
        result = reading.result(timeout=5)
    assert result.value.degraded and not result.tokens
    assert finalized(store.read_retrieval_publication(query(semantic_query="topic"))) is None


def test_upsert_overlapping_new_revision_never_clears_its_dirty_marker() -> None:
    store, repo, index, backend = setup()
    save(store, "A")
    record = repo.get("A")
    assert record is not None
    backend.slow = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        updating = pool.submit(index.upsert, record)
        try:
            assert backend.entered.wait(5)
            changed = replace(record, revision=1)
            assert repo.save_record(changed, expected_revision=0)
        finally:
            backend.release.set()
        with pytest.raises(RuntimeError):
            updating.result(timeout=5)
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    backend.slow = False
    index.upsert(changed)
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    index.rebuild()
    with pytest.raises(RuntimeError):
        index.upsert(record)
    assert backend.records["A"] == changed
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)


def test_initial_registration_and_failed_rebuild_cannot_claim_current() -> None:
    class FailedRebuild(Index):
        def rebuild(self, records: tuple[MemoryRecord, ...]) -> None:
            raise RuntimeError("試験用の修復失敗")

    repo = InMemoryMemoryRepository()
    index = FinalizableMemorySemanticIndex(FailedRebuild())
    store = MemoryStoreAuthority(repo, index, ranking_policy=retrieval_policy())
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    save(store, "A")
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    with pytest.raises(RuntimeError):
        index.rebuild()
    unavailable(store, FinalizationFailure.PARTICIPANT_UNAVAILABLE)
    assert finalized(store.read_retrieval_publication(query())) is None
