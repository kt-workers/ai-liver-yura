"""Memoryごとの最終確定と、更新中の非待機拒否を検証する。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from threading import Event

from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationParticipant,
    AuthorityFinalizationRequest,
    AuthorityGenerationToken,
    AuthorityReadPublication,
    FinalizationFailure,
)
from app.domain.memory import (
    MemoryRelation,
    MemoryRelationKind,
    MemoryStoreAuthority,
    MemoryWriteRequest,
)
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from tests.domain.memory.test_memory_store_retrieval import NOW, authority, candidate
from tests.domain.memory.test_semantic_assertions import SEMANTICS


class Consumer:
    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, "memory-test-consumer", 90)
        self.operation = self.participant.register_operation(self, "accept", self.accept)
        self.calls = 0

    def accept(self, value: int, now: datetime) -> int:
        self.calls += 1
        return value


def finalize(
    publication: AuthorityReadPublication[MemorySemanticAssertionEntry],
) -> FinalizationFailure | None:
    consumer = Consumer()
    result = AuthorityFinalizationFence().finalize(
        AuthorityFinalizationRequest(
            publication.tokens, consumer.participant, consumer.operation, 1
        )
    )
    assert consumer.calls == (1 if result.failure is None else 0)
    return result.failure


def seed(store: MemoryStoreAuthority, memory_id: str) -> None:
    result = store.write(
        MemoryWriteRequest(
            replace(candidate(memory_id, value=memory_id), assertion_semantics=SEMANTICS)
        )
    )
    assert result.record is not None


def test_record_and_relation_invalidation_is_local() -> None:
    store, repo = authority()
    for mid in ("A", "B", "C"):
        seed(store, mid)
    a = store.read_semantic_assertion_publication("A", 0)
    b = store.read_semantic_assertion_publication("B", 0)
    assert a.value.assertion is not None and a.tokens and finalize(a) is None
    c = repo.get("C")
    assert c is not None
    assert repo.save_record(replace(c, revision=1), expected_revision=0)
    assert finalize(a) is None and finalize(b) is None
    record = repo.get("A")
    assert record is not None
    assert repo.save_record(replace(record, revision=1), expected_revision=0)
    assert finalize(a) is FinalizationFailure.GENERATION_MISMATCH
    fresh = store.read_semantic_assertion_publication("A", 1)
    assert repo.save_relation(
        MemoryRelation("ab", "A", "B", MemoryRelationKind.CONTRADICTS, ("fact",), NOW)
    )
    unchanged = repo.get("A")
    assert unchanged is not None and unchanged.revision == 1
    assert finalize(fresh) is FinalizationFailure.GENERATION_MISMATCH
    assert finalize(b) is FinalizationFailure.GENERATION_MISMATCH
    assert store.read_semantic_assertion_publication("A", 1).tokens == ()


def test_failed_update_also_invalidates_and_unavailable_has_no_token() -> None:
    store, repo = authority()
    seed(store, "A")
    old = store.read_semantic_assertion_publication("A", 0)
    record = repo.get("A")
    assert record is not None
    assert not repo.save_record(record, expected_revision=0)
    assert finalize(old) is FinalizationFailure.GENERATION_MISMATCH
    repo.available = False
    assert not store.read_semantic_assertion_publication("A").tokens
    repo.available = True
    assert not store.read_semantic_assertion_publication("missing").tokens
    assert not store.read_semantic_assertion_publication("A", 999).tokens


def test_mutation_busy_rejects_old_finalization_without_blocking_other_memory() -> None:
    store, repo = authority()
    seed(store, "A")
    seed(store, "C")
    a = store.read_semantic_assertion_publication("A")
    c = store.read_semantic_assertion_publication("C")
    entered, release = Event(), Event()

    def slow_update() -> None:
        with repo.semantic_guards.mutation({"A"}):
            entered.set()
            assert release.wait(5)
            record = repo.get("A")
            assert record is not None
            assert repo.save_record(replace(record, revision=1), expected_revision=0)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(slow_update)
        try:
            assert entered.wait(5)
            assert finalize(a) is FinalizationFailure.PARTICIPANT_BUSY
            assert finalize(c) is None
            other = repo.get("C")
            assert other is not None
            assert repo.save_record(replace(other, revision=1), expected_revision=0)
        finally:
            release.set()
        future.result(timeout=5)
    assert finalize(a) is FinalizationFailure.GENERATION_MISMATCH


def test_existing_participant_capacity_is_not_bypassed() -> None:
    store, _ = authority()
    tokens: list[AuthorityGenerationToken] = []
    for n in range(16):
        mid = str(n)
        seed(store, mid)
        tokens.extend(store.read_semantic_assertion_publication(mid).tokens)
    consumer = Consumer()
    result = AuthorityFinalizationFence().finalize(
        AuthorityFinalizationRequest(tuple(tokens), consumer.participant, consumer.operation, 1)
    )
    assert result.failure is FinalizationFailure.INVALID_LOCK_CONFIGURATION
    assert consumer.calls == 0
