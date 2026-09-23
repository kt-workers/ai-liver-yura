"""検索集合の現在性を、既存Fenceと登録Repositoryの変更経路で検証する。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from typing import TypeVar

import pytest

from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationRequest,
    AuthorityReadPublication,
    FinalizationError,
    FinalizationFailure,
)
from app.domain.memory import (
    MemoryLifecycle,
    MemoryRecord,
    MemoryRelation,
    MemoryRelationKind,
    MemoryStoreAuthority,
    MemoryWriteRequest,
)
from app.domain.memory.ranking import MemorySemanticRelevance
from app.domain.memory.repository import (
    FinalizableMemorySemanticIndex,
    InMemoryMemoryRepository,
    MemoryRepositorySnapshot,
)
from tests.domain.memory.policy_fixtures import retrieval_policy
from tests.domain.memory.test_finalization_publication import Consumer
from tests.domain.memory.test_memory_store_retrieval import NOW, authority, candidate, query
from tests.domain.memory.test_semantic_assertions import SEMANTICS

T = TypeVar("T")


def finalized(publication: AuthorityReadPublication[T]) -> FinalizationFailure | None:
    consumer = Consumer()
    result = AuthorityFinalizationFence().finalize(
        AuthorityFinalizationRequest(
            publication.tokens, consumer.participant, consumer.operation, 1
        )
    )
    assert consumer.calls == (1 if result.failure is None else 0)
    return result.failure


def save(store: MemoryStoreAuthority, mid: str, subject: str = "user:1") -> None:
    result = store.write(MemoryWriteRequest(candidate(mid, value=mid, subject=subject)))
    assert result.record is not None


def test_new_matching_memory_invalidates_old_set_but_unrelated_write_does_not() -> None:
    store, repo = authority()
    save(store, "A")
    q = query(subject_refs=("user:1",), max_estimated_tokens=10000)
    old = store.read_retrieval_publication(q)
    assert [x.memory_id for x in old.value.items] == ["A"]
    assert len(old.tokens) == 2 and finalized(old) is None
    save(store, "C", "other")
    c = repo.get("C")
    assert c is not None
    assert repo.save_record(replace(c, revision=1), expected_revision=0)
    assert finalized(old) is None
    save(store, "B")
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
    new = store.read_retrieval_publication(q)
    assert {x.memory_id for x in new.value.items} == {"A", "B"}
    assert finalized(new) is None


@pytest.mark.parametrize("change", ["archived", "superseded", "semantics", "confidence", "subject"])
def test_existing_candidate_mutations_invalidate(change: str) -> None:
    store, repo = authority()
    save(store, "A")
    old = store.read_retrieval_publication(query(subject_refs=("user:1",)))
    a = repo.get("A")
    assert a is not None
    updated = replace(a, revision=1)
    if change == "archived":
        updated = replace(updated, lifecycle=MemoryLifecycle.ARCHIVED)
    elif change == "superseded":
        updated = replace(updated, lifecycle=MemoryLifecycle.SUPERSEDED)
    elif change == "semantics":
        updated = replace(updated, assertion_semantics=SEMANTICS)
    elif change == "confidence":
        updated = replace(updated, confidence=replace(a.confidence, value=0.1))
    else:
        updated = replace(updated, content=replace(a.content, subject_ref="other"))
    assert repo.save_record(updated, expected_revision=0)
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH


def test_eligibility_transitions_are_fenced_even_when_id_publication_has_no_token() -> None:
    from app.domain.contracts import SemanticSubjectIdentity, SemanticSubjectKind

    store, repo = authority()
    save(store, "A")
    first = store.read_retrieval_publication(query())
    assert not store.read_semantic_assertion_publication("A").tokens
    a = repo.get("A")
    assert a is not None
    updated = replace(
        a,
        revision=1,
        assertion_semantics=SEMANTICS,
        subject_identity=SemanticSubjectIdentity(SemanticSubjectKind.REFERENCE, "user:1"),
    )
    assert repo.save_record(updated, expected_revision=0)
    assert store.read_semantic_assertion_publication("A").tokens
    assert finalized(first) is FinalizationFailure.GENERATION_MISMATCH
    second = store.read_retrieval_publication(query())
    assert repo.save_record(
        replace(updated, revision=2, assertion_semantics=None), expected_revision=1
    )
    assert not store.read_semantic_assertion_publication("A").tokens
    assert finalized(second) is FinalizationFailure.GENERATION_MISMATCH


def test_relation_change_and_previously_excluded_candidate_are_observed() -> None:
    store, repo = authority()
    for mid in ("A", "B"):
        save(store, mid)
    before = store.read_retrieval_publication(query())
    assert repo.save_relation(
        MemoryRelation("ab", "A", "B", MemoryRelationKind.CONTRADICTS, ("fact",), NOW)
    )
    assert finalized(before) is FinalizationFailure.GENERATION_MISMATCH
    assert not store.read_retrieval_publication(query()).value.items
    a = repo.get("A")
    assert a is not None
    c = replace(a, memory_id="C", revision=0, lifecycle=MemoryLifecycle.ARCHIVED)
    assert repo.save_record(c, expected_revision=None)
    empty = store.read_retrieval_publication(query())
    assert repo.save_record(
        replace(c, revision=1, lifecycle=MemoryLifecycle.ACTIVE), expected_revision=0
    )
    assert finalized(empty) is FinalizationFailure.GENERATION_MISMATCH
    assert [x.memory_id for x in store.read_retrieval_publication(query()).value.items] == ["C"]


def test_registered_purge_uses_old_scope_without_changing_retention_policy() -> None:
    store, repo = authority()
    save(store, "A")
    old = store.read_retrieval_publication(query())
    a = repo.get("A")
    assert a is not None
    # retention所有者の登録境界を模擬し、消費側の独自世代を作らない。
    with repo.semantic_guards.mutation({"A"}):
        with repo.semantic_guards.retrieval_mutation((a,)):
            del repo._records["A"]
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
    assert not store.read_retrieval_publication(query()).value.items


@pytest.mark.parametrize("max_items,budget", [(1, 10000), (8, 1), (8, 10000)])
def test_publication_preserves_exact_retrieval_bounds(max_items: int, budget: int) -> None:
    store, _ = authority()
    for mid in ("A", "B"):
        save(store, mid)
    q = query(max_items=max_items, max_estimated_tokens=budget)
    assert store.read_retrieval_publication(q).value == store.retrieve(q)


def test_policy_generation_invalidates_without_modifying_records() -> None:
    store, _ = authority()
    save(store, "A")
    old = store.read_retrieval_publication(query())
    policy = retrieval_policy()
    store.update_retrieval_ranking_policy(
        replace(policy, policy_revision=policy.policy_revision + 1)
    )
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
    new = store.read_retrieval_publication(query())
    assert new.value.ranking_policy_revision == policy.policy_revision + 1
    assert finalized(new) is None


def test_matching_mutation_is_busy_while_unrelated_retrieval_and_fence_continue() -> None:
    store, repo = authority()
    save(store, "A")
    save(store, "C", "other")
    q = query(subject_refs=("user:1",))
    old = store.read_retrieval_publication(q)
    unrelated = store.read_retrieval_publication(query(subject_refs=("other",)))
    a = repo.get("A")
    assert a is not None
    entered, release = Event(), Event()

    def mutation() -> None:
        with repo.semantic_guards.mutation({"A"}):
            with repo.semantic_guards.retrieval_mutation((a,)):
                entered.set()
                assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(mutation)
        try:
            assert entered.wait(5)
            assert finalized(old) is FinalizationFailure.PARTICIPANT_BUSY
            with pytest.raises(FinalizationError) as error:
                store.read_retrieval_publication(q)
            assert error.value.failure is FinalizationFailure.PARTICIPANT_BUSY
            assert finalized(unrelated) is None
            assert (
                finalized(store.read_retrieval_publication(query(subject_refs=("other",)))) is None
            )
        finally:
            release.set()
        future.result(timeout=5)
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH


class Index:
    def rebuild(self, records: tuple[MemoryRecord, ...]) -> None:
        pass

    def upsert(self, record: object) -> None:
        pass

    def related_scores(self, query: str, *, limit: int) -> tuple[MemorySemanticRelevance, ...]:
        return (MemorySemanticRelevance("A", 0.5),)


def test_index_generation_only_participates_in_semantic_queries() -> None:
    repo = InMemoryMemoryRepository()
    index = FinalizableMemorySemanticIndex(Index())
    store = MemoryStoreAuthority(repo, index, ranking_policy=retrieval_policy())
    save(store, "A")
    index.rebuild()
    normal = store.read_retrieval_publication(query())
    semantic = store.read_retrieval_publication(query(semantic_query="topic"))
    assert len(semantic.tokens) == 3
    a = repo.get("A")
    assert a is not None
    index.upsert(a)
    assert finalized(normal) is None
    assert finalized(semantic) is FinalizationFailure.GENERATION_MISMATCH
    raw = MemoryStoreAuthority(repo, Index(), ranking_policy=retrieval_policy())
    with pytest.raises(FinalizationError) as error:
        raw.read_retrieval_publication(query(semantic_query="topic"))
    assert error.value.failure is FinalizationFailure.PARTICIPANT_UNSUPPORTED


def test_degraded_view_is_preserved_without_finalizable_success() -> None:
    store, repo = authority()
    repo.available = False
    q = query()
    result = store.read_retrieval_publication(q)
    assert result.value == store.retrieve(q) and result.value.degraded
    assert not result.tokens


def test_existing_participant_limit_counts_set_and_policy_tokens() -> None:
    store, _ = authority()
    publications = [store.read_retrieval_publication(query()) for _ in range(15)]
    consumer = Consumer()
    tokens = tuple(token for p in publications for token in p.tokens)
    result = AuthorityFinalizationFence().finalize(
        AuthorityFinalizationRequest(tokens, consumer.participant, consumer.operation, 1)
    )
    assert result.failure is FinalizationFailure.INVALID_LOCK_CONFIGURATION
    assert consumer.calls == 0


def test_failed_write_releases_pending_registration_and_rejects_old_token() -> None:
    store, repo = authority()
    save(store, "A")
    old = store.read_retrieval_publication(query())
    a = repo.get("A")
    assert a is not None
    assert not repo.save_record(replace(a, revision=9), expected_revision=0)
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
    assert finalized(store.read_retrieval_publication(query())) is None
    assert not repo.semantic_guards._pending_retrieval_mutations


def test_publication_registry_reclaims_released_tokens() -> None:
    import gc
    import weakref

    store, repo = authority()
    publication = store.read_retrieval_publication(query())
    participant = weakref.ref(publication.tokens[0]._participant)
    del publication
    gc.collect()
    assert participant() is None
    assert not repo.semantic_guards._retrievals


def test_policy_change_during_snapshot_cannot_publish_current_old_ranking() -> None:
    entered, release = Event(), Event()

    class PausedRepository(InMemoryMemoryRepository):
        def snapshot(self) -> MemoryRepositorySnapshot:
            entered.set()
            assert release.wait(5)
            return super().snapshot()

    repo = PausedRepository()
    store = MemoryStoreAuthority(repo, ranking_policy=retrieval_policy())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(store.read_retrieval_publication, query())
        try:
            assert entered.wait(5)
            policy = retrieval_policy()
            store.update_retrieval_ranking_policy(
                replace(policy, policy_revision=policy.policy_revision + 1)
            )
        finally:
            release.set()
        from app.domain.memory.ranking import MemoryRetrievalError, MemoryRetrievalFailureCode

        with pytest.raises(MemoryRetrievalError) as error:
            future.result(timeout=5)
        assert error.value.code is MemoryRetrievalFailureCode.POLICY_STALE


def test_write_waiting_on_snapshot_invalidates_read_before_final_commit() -> None:
    entered, release, writing = Event(), Event(), Event()

    class PausedRepository(InMemoryMemoryRepository):
        paused = False

        def snapshot(self) -> MemoryRepositorySnapshot:
            snapshot = super().snapshot()
            if self.paused:
                entered.set()
                assert release.wait(5)
            return snapshot

    repo = PausedRepository()
    store = MemoryStoreAuthority(repo, ranking_policy=retrieval_policy())
    save(store, "A")
    record = repo.get("A")
    assert record is not None
    b = replace(record, memory_id="B")
    repo.paused = True

    def write() -> bool:
        writing.set()
        return repo.save_record(b, expected_revision=None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(store.read_retrieval_publication, query(max_estimated_tokens=10000))
        try:
            assert entered.wait(5)
            mutation = pool.submit(write)
            assert writing.wait(5)
        finally:
            release.set()
        old = reading.result(timeout=5)
        assert mutation.result(timeout=5)
    assert [item.memory_id for item in old.value.items] == ["A"]
    assert finalized(old) is FinalizationFailure.GENERATION_MISMATCH
    repo.paused = False
    current = store.read_retrieval_publication(query(max_estimated_tokens=10000))
    assert {item.memory_id for item in current.value.items} == {"A", "B"}
    assert finalized(current) is None
