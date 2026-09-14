"""Memoryの主体metadataを推測せず、保存から公開までexactに維持する。"""

import json
from dataclasses import replace
from typing import Any

import pytest

from app.domain.contracts import SemanticSubjectIdentity as Identity
from app.domain.contracts import SemanticSubjectKind as Kind
from app.domain.memory import (
    MemoryDisposition,
    MemoryRelationKind,
    MemoryWriteRequest,
    project_memory_semantic_assertions,
)
from app.domain.memory import (
    MemorySemanticAssertionUnavailableReason as Reason,
)
from app.infrastructure.persistence import PersistenceError, PersistenceFailureCode
from app.infrastructure.persistence.memory_codec import decode_memory_record, encode_memory_record
from tests.domain.memory.test_memory_store_retrieval import authority, candidate, query
from tests.domain.memory.test_semantic_assertions import SEMANTICS


@pytest.mark.parametrize("kind", list(Kind))
def test_exact_subject_transport_and_publication(kind: Kind) -> None:
    identity = Identity(kind, "user:1")
    source = replace(candidate(), assertion_semantics=SEMANTICS, subject_identity=identity)
    store, _ = authority()
    written = store.write(MemoryWriteRequest(source))
    assert written.record is not None and written.record.subject_identity is identity
    evidence = store.retrieve(query())
    assert evidence.items[0].subject_identity is identity
    assertion = project_memory_semantic_assertions(evidence).entries[0].assertion
    assert assertion is not None and assertion.subject_identity is identity
    assert assertion.subject_ref == assertion.content.subject_ref == identity.subject_ref
    publication = store.read_semantic_assertion_publication(written.record.memory_id, 0)
    assert publication.tokens and publication.value.assertion == assertion
    assert decode_memory_record(encode_memory_record(written.record)) == written.record


@pytest.mark.parametrize("subject", [None, "user:1"])
@pytest.mark.parametrize("semantics", [None, SEMANTICS])
def test_unresolved_is_saved_without_backfill(subject: str | None, semantics: Any) -> None:
    source = replace(candidate(subject=subject), assertion_semantics=semantics)
    store, repository = authority()
    written = store.write(MemoryWriteRequest(source))
    assert written.record is not None and written.record.subject_identity is None
    before = repository.snapshot()
    result = store.read_semantic_assertion_publication(written.record.memory_id)
    assert result.tokens == () and result.value.assertion is None
    assert result.value.unavailable_reason is (
        Reason.SEMANTICS_UNRESOLVED if semantics is None else Reason.SUBJECT_UNRESOLVED
    )
    assert repository.snapshot() == before


@pytest.mark.parametrize("layer", ["candidate", "record", "evidence", "assertion"])
@pytest.mark.parametrize("invalid", ["wrong_type", "no_ref", "mismatch"])
def test_structural_consistency_all_layers(layer: str, invalid: str) -> None:
    source = replace(
        candidate(),
        assertion_semantics=SEMANTICS,
        subject_identity=Identity(Kind.REFERENCE, "user:1"),
    )
    store, _ = authority()
    record = store.write(MemoryWriteRequest(source)).record
    assert record is not None
    evidence = store.retrieve(query()).items[0]
    assertion = store.read_semantic_assertion(record.memory_id).assertion
    assert assertion is not None
    value: Any = {
        "candidate": source,
        "record": record,
        "evidence": evidence,
        "assertion": assertion,
    }[layer]
    identity: Any = "user:1" if invalid == "wrong_type" else Identity(Kind.SELF, "other")
    content = replace(source.content, subject_ref=None) if invalid == "no_ref" else source.content
    with pytest.raises(ValueError):
        replace(value, content=content, subject_identity=identity)


def test_duplicate_identity_does_not_migrate_legacy_or_reclassify() -> None:
    store, repository = authority()
    source = replace(candidate("legacy"), assertion_semantics=SEMANTICS)
    legacy = store.write(MemoryWriteRequest(source)).record
    assert legacy is not None
    for kind in Kind:
        typed = replace(source, candidate_id=kind.value, subject_identity=Identity(kind, "user:1"))
        assert store.write(MemoryWriteRequest(typed)).disposition is MemoryDisposition.STORE_NEW
        assert (
            store.write(MemoryWriteRequest(typed)).disposition is MemoryDisposition.NOOP_DUPLICATE
        )
        newer = replace(
            typed,
            candidate_id="merge-" + kind.value,
            provenance=replace(typed.provenance, source_fact_refs=("new-fact",)),
        )
        merged = store.write(MemoryWriteRequest(newer))
        assert merged.disposition is MemoryDisposition.MERGE_PROVENANCE
        assert (
            merged.record is not None and merged.record.subject_identity == typed.subject_identity
        )
    assert repository.get("legacy") == legacy
    assert len(repository.snapshot().records) == 3


@pytest.mark.parametrize("relation", list(MemoryRelationKind))
def test_related_write_keeps_identity(relation: MemoryRelationKind) -> None:
    store, _ = authority()
    first = store.write(MemoryWriteRequest(candidate())).record
    assert first is not None
    source = replace(
        candidate("related", value="changed"),
        assertion_semantics=SEMANTICS,
        subject_identity=Identity(Kind.REFERENCE, "user:1"),
    )
    result = store.write(MemoryWriteRequest(source, 0, first.memory_id, relation))
    assert result.record is not None and result.record.subject_identity is source.subject_identity


def test_evidence_capacity_counts_metadata_and_preserves_ranking_filter() -> None:
    store, _ = authority()
    raw = replace(candidate("legacy"), assertion_semantics=SEMANTICS)
    typed = replace(raw, candidate_id="typed", subject_identity=Identity(Kind.REFERENCE, "user:1"))
    store.write(MemoryWriteRequest(raw))
    store.write(MemoryWriteRequest(typed))
    view = store.retrieve(query(max_estimated_tokens=4000, subject_refs=("user:1",)))
    assert len(view.items) == 2
    by_id = {i.memory_id: i for i in view.items}
    assert by_id["legacy"].score == by_id["typed"].score
    assert by_id["typed"].estimated_tokens > by_id["legacy"].estimated_tokens
    assert not store.retrieve(query(subject_refs=("other",))).items
    first = view.items[0]
    low, high = 1, 4000
    while low < high:
        middle = (low + high) // 2
        if store.retrieve(query(max_estimated_tokens=middle)).items:
            high = middle
        else:
            low = middle + 1
    bounded = store.retrieve(query(max_estimated_tokens=low))
    assert bounded.truncated and bounded.items == (first,)
    assert not store.retrieve(query(max_estimated_tokens=low - 1)).items


@pytest.mark.parametrize(
    "identity", [None, Identity(Kind.SELF, "user:1"), Identity(Kind.REFERENCE, "user:1")]
)
def test_codec_roundtrip_and_content_shape(identity: Identity | None) -> None:
    source = replace(candidate(), subject_identity=identity)
    store, _ = authority()
    record = store.write(MemoryWriteRequest(source)).record
    assert record is not None
    encoded = encode_memory_record(record)
    assert decode_memory_record(encoded) == record
    data = json.loads(encoded)
    assert "subject_identity" not in data["content"]
    del data["subject_identity"]
    legacy = decode_memory_record(json.dumps(data))
    assert legacy.subject_identity is None and legacy.content == record.content


@pytest.mark.parametrize(
    "identity",
    [
        {},
        [],
        "SELF",
        1,
        True,
        {"kind": "UNKNOWN", "subject_ref": "user:1"},
        {"kind": "SELF"},
        {"subject_ref": "user:1"},
        {"kind": "SELF", "subject_ref": "user:1", "extra": False},
        {"kind": "SELF", "subject_ref": "other"},
        {"kind": "REFERENCE", "subject_ref": None},
        {"kind": 1, "subject_ref": "user:1"},
    ],
)
def test_codec_malformed_identity_is_corrupt(identity: object) -> None:
    store, _ = authority()
    record = store.write(MemoryWriteRequest(candidate())).record
    assert record is not None
    data = json.loads(encode_memory_record(record))
    data["subject_identity"] = identity
    with pytest.raises(PersistenceError) as error:
        decode_memory_record(json.dumps(data))
    assert error.value.code is PersistenceFailureCode.CORRUPT_RECORD
