"""意味を推測しないMemory公開と、current record/relationの再照合。"""

import json
from dataclasses import replace

import pytest

from app.domain.memory import (
    MemoryAssertionCertainty as C,
)
from app.domain.memory import (
    MemoryAssertionPolarity as P,
)
from app.domain.memory import (
    MemoryAssertionSemantics as S,
)
from app.domain.memory import (
    MemoryAssertionTemporalMeaning as T,
)
from app.domain.memory import (
    MemoryConfidence,
    MemoryDisposition,
    MemoryFreshnessState,
    MemoryKind,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryRelationKind,
    MemorySourceKind,
    MemoryWriteRequest,
    project_memory_semantic_assertions,
)
from app.domain.memory import (
    MemorySemanticAssertionUnavailableReason as R,
)
from app.infrastructure.persistence import PersistenceError
from app.infrastructure.persistence.memory_codec import decode_memory_record, encode_memory_record
from tests.domain.memory.test_memory_store_retrieval import NOW, authority, candidate, query

SEMANTICS = S(P.AFFIRM, C.LIKELY, T.CURRENT)


@pytest.mark.parametrize("polarity", list(P))
@pytest.mark.parametrize("confidence", [0.1, 0.5, 1.0])
def test_explicit_meaning_roundtrip_and_publication(polarity: P, confidence: float) -> None:
    store, _ = authority()
    semantics = replace(SEMANTICS, polarity=polarity)
    source = replace(
        candidate(),
        assertion_semantics=semantics,
        confidence=MemoryConfidence(confidence, "source"),
    )
    result = store.write(MemoryWriteRequest(source))
    assert result.record is not None
    assert decode_memory_record(encode_memory_record(result.record)) == result.record
    evidence = store.retrieve(query())
    assert evidence.items[0].memory_revision == result.record.revision
    assert evidence.items[0].assertion_semantics == semantics
    view = project_memory_semantic_assertions(evidence)
    assertion = view.entries[0].assertion
    assert assertion is not None
    assert assertion.polarity is polarity and assertion.certainty is C.LIKELY
    assert assertion.temporal_meaning is T.CURRENT
    assert assertion.confidence.value == confidence
    assert assertion.subject_ref == source.content.subject_ref
    assert (
        assertion.predicate == source.content.predicate and assertion.value == source.content.value
    )
    assert assertion.temporal_scope_ref == source.content.temporal_scope_ref
    assert assertion.qualifiers == source.content.qualifiers
    assert assertion.provenance == (source.provenance,)
    assert (
        store.read_semantic_assertion(result.record.memory_id, result.record.revision).assertion
        == assertion
    )


@pytest.mark.parametrize(
    "other",
    [
        None,
        S(P.NEGATE, C.LIKELY, T.CURRENT),
        S(P.AFFIRM, C.CERTAIN, T.CURRENT),
        S(P.AFFIRM, C.LIKELY, T.HISTORICAL),
    ],
)
def test_semantics_is_part_of_exact_duplicate_identity(other: S | None) -> None:
    store, repository = authority()
    first = replace(candidate(), assertion_semantics=SEMANTICS)
    assert store.write(MemoryWriteRequest(first)).disposition is MemoryDisposition.STORE_NEW
    second = replace(candidate("second", source="fact:2"), assertion_semantics=other)
    assert store.write(MemoryWriteRequest(second)).disposition is MemoryDisposition.STORE_NEW
    third = replace(candidate("third", source="fact:3"), assertion_semantics=SEMANTICS)
    merged = store.write(MemoryWriteRequest(third))
    assert merged.disposition is MemoryDisposition.MERGE_PROVENANCE
    assert merged.record is not None and merged.record.assertion_semantics == SEMANTICS
    assert len(repository.snapshot().records) == 2


@pytest.mark.parametrize(
    "case,reason",
    [
        ("semantics", R.SEMANTICS_UNRESOLVED),
        ("subject", R.SUBJECT_UNRESOLVED),
        ("stale", R.STALE),
        ("archived", R.INACTIVE_LIFECYCLE),
        ("superseded", R.INACTIVE_LIFECYCLE),
        ("provenance", R.PROVENANCE_UNAVAILABLE),
        ("historical_current", R.TEMPORAL_INCONSISTENCY),
    ],
)
def test_unavailable_preserves_reason_without_fallback(case: str, reason: R) -> None:
    store, repository = authority()
    c = replace(candidate(kind=MemoryKind.WORKING), assertion_semantics=SEMANTICS)
    if case == "semantics":
        c = replace(c, assertion_semantics=None)
    if case == "subject":
        c = replace(c, content=replace(c.content, subject_ref=None))
    if case == "stale":
        c = replace(c, temporal=replace(c.temporal, freshness=MemoryFreshnessState.STALE))
    if case == "historical_current":
        c = replace(c, temporal=replace(c.temporal, freshness=MemoryFreshnessState.HISTORICAL))
    if case == "provenance":
        c = replace(
            c, provenance=MemoryProvenance(MemorySourceKind.TYPED_FACT, (), (), None, None, NOW)
        )
    written = store.write(MemoryWriteRequest(c))
    assert written.record is not None
    if case in ("archived", "superseded"):
        updated = replace(written.record, revision=1, lifecycle=MemoryLifecycle(case))
        assert repository.save_record(updated, expected_revision=0)
    entry = store.read_semantic_assertion(c.candidate_id)
    assert entry.assertion is None and entry.unavailable_reason is reason
    if case != "archived":
        evidence = store.retrieve(query())
        assert len(evidence.items) == 1
        assert project_memory_semantic_assertions(evidence).entries[0].unavailable_reason is reason


@pytest.mark.parametrize("temporal", [T.HISTORICAL, T.TIME_BOUNDED])
def test_historical_meaning_is_preserved(temporal: T) -> None:
    store, _ = authority()
    c = replace(
        candidate(freshness=MemoryFreshnessState.HISTORICAL),
        assertion_semantics=replace(SEMANTICS, temporal_meaning=temporal),
    )
    store.write(MemoryWriteRequest(c))
    assertion = store.read_semantic_assertion(c.candidate_id).assertion
    assert assertion is not None and assertion.temporal_meaning is temporal


def test_current_relation_is_checked_even_when_record_revision_matches() -> None:
    store, repository = authority()
    c = replace(candidate(), assertion_semantics=SEMANTICS)
    store.write(MemoryWriteRequest(c))
    previous = store.retrieve(query())
    assert project_memory_semantic_assertions(previous).entries[0].assertion is not None
    other = replace(candidate("other", value="different"), assertion_semantics=SEMANTICS)
    store.write(MemoryWriteRequest(other, 0, c.candidate_id, MemoryRelationKind.CONTRADICTS))
    current = repository.get(c.candidate_id)
    assert current is not None and current.revision == previous.items[0].memory_revision
    for memory_id in (c.candidate_id, "other"):
        assert store.read_semantic_assertion(memory_id, 0).unavailable_reason is R.CONFLICTED
    projected = project_memory_semantic_assertions(
        store.retrieve(query(include_conflicted=True, max_estimated_tokens=4096))
    )
    assert all(e.unavailable_reason is R.CONFLICTED for e in projected.entries)


def test_exact_read_stale_missing_and_repository_unavailable() -> None:
    store, repository = authority()
    c = replace(candidate(), assertion_semantics=SEMANTICS)
    store.write(MemoryWriteRequest(c))
    evidence = store.retrieve(query())
    store.write(
        MemoryWriteRequest(
            replace(
                c, candidate_id="new", provenance=replace(c.provenance, source_fact_refs=("new",))
            )
        )
    )
    stale = store.read_semantic_assertion(c.candidate_id, evidence.items[0].memory_revision)
    assert stale.unavailable_reason is R.REVISION_STALE and stale.assertion is None
    assert stale.memory_revision == 1
    assert store.read_semantic_assertion("missing").unavailable_reason is R.SOURCE_NOT_FOUND
    repository.available = False
    assert (
        store.read_semantic_assertion(c.candidate_id).unavailable_reason is R.REPOSITORY_UNAVAILABLE
    )


def test_ranking_truncation_and_degraded_whole_view() -> None:
    store, _ = authority()
    for i in range(3):
        store.write(
            MemoryWriteRequest(replace(candidate(str(i), value=i), assertion_semantics=SEMANTICS))
        )
    source = store.retrieve(query(max_items=2, max_estimated_tokens=4096))
    view = project_memory_semantic_assertions(source)
    assert view.source is source and view.truncated and not view.degraded
    assert [e.memory_id for e in view.entries] == [i.memory_id for i in source.items]
    assert all(e.assertion is not None and e.assertion.certainty is C.LIKELY for e in view.entries)
    degraded = store.retrieve(query(semantic_query="query", max_estimated_tokens=4096))
    result = project_memory_semantic_assertions(degraded)
    assert result.unavailable_reason is R.DEGRADED_VIEW
    assert all(
        e.assertion is None and e.unavailable_reason is R.DEGRADED_VIEW for e in result.entries
    )
    empty = project_memory_semantic_assertions(replace(degraded, items=()))
    assert empty.unavailable_reason is R.DEGRADED_VIEW and empty.entries == ()


def test_token_budget_counts_revision_and_semantics() -> None:
    store, _ = authority()
    result = store.write(MemoryWriteRequest(replace(candidate(), assertion_semantics=SEMANTICS)))
    assert result.record is not None
    payload = store._evidence_payload(result.record, {}, 0.5)
    assert payload["memory_revision"] == 0 and payload["assertion_semantics"] == SEMANTICS.to_dict()
    full = store._estimate_tokens(payload)
    del payload["assertion_semantics"]
    del payload["memory_revision"]
    assert full > store._estimate_tokens(payload)
    # 境界を探索し、追加field込みの推定値でitemを丸ごと切ることを確認する。
    limit = next(
        n
        for n in range(1, query().max_estimated_tokens + 1)
        if store.retrieve(query(max_estimated_tokens=n)).items
    )
    assert not store.retrieve(query(max_estimated_tokens=limit - 1)).items
    assert store.retrieve(query(max_estimated_tokens=limit - 1)).truncated
    assert len(store.retrieve(query(max_estimated_tokens=limit)).items) == 1


def test_old_record_without_facets_is_not_promoted() -> None:
    store, _ = authority()
    result = store.write(MemoryWriteRequest(candidate()))
    assert result.record is not None
    data = json.loads(encode_memory_record(result.record))
    del data["assertion_semantics"]
    restored = decode_memory_record(json.dumps(data))
    assert restored.assertion_semantics is None and restored == result.record
    for malformed in ({}, {"polarity": "unknown"}, "affirm"):
        data["assertion_semantics"] = malformed
        with pytest.raises(PersistenceError):
            decode_memory_record(json.dumps(data))


@pytest.mark.parametrize("field", ["claims_actual_speech", "claims_executed_activity"])
def test_explicit_facets_do_not_bypass_actual_evidence_guard(field: str) -> None:
    with pytest.raises(ValueError):
        replace(candidate(), assertion_semantics=SEMANTICS,
                claims_actual_speech=field == "claims_actual_speech",
                claims_executed_activity=field == "claims_executed_activity")
