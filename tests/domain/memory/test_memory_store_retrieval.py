from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.contracts.common import JsonValue
from app.domain.memory import (
    InMemoryMemoryRepository,
    MemoryConfidence,
    MemoryContent,
    MemoryDegradationReason,
    MemoryDisposition,
    MemoryFreshnessState,
    MemoryKind,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryRecord,
    MemoryRelation,
    MemoryRelationKind,
    MemoryRetrievalQuery,
    MemorySourceKind,
    MemoryStoreAuthority,
    MemoryTemporalState,
    MemoryWriteRequest,
    ValidatedMemoryCandidate,
)
from app.domain.memory.repository import MemoryRepositorySnapshot

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def candidate(
    candidate_id: str = "candidate:1",
    *,
    kind: MemoryKind = MemoryKind.SEMANTIC,
    value: JsonValue = "game-a",
    source: str = "fact:1",
    source_kind: MemorySourceKind = MemorySourceKind.TYPED_FACT,
    freshness: MemoryFreshnessState = MemoryFreshnessState.FRESH,
    subject: str | None = "user:1",
) -> ValidatedMemoryCandidate:
    return ValidatedMemoryCandidate(
        candidate_id,
        kind,
        MemoryContent("preference", value, subject),
        MemoryProvenance(source_kind, (), (source,), None, NOW, NOW),
        MemoryConfidence(0.8, "trusted-source"),
        MemoryTemporalState(freshness, observed_at=NOW),
        NOW,
        importance_hint=0.5,
    )


def authority() -> tuple[MemoryStoreAuthority, InMemoryMemoryRepository]:
    repository = InMemoryMemoryRepository()
    return MemoryStoreAuthority(repository), repository


def query(
    *,
    memory_kinds: tuple[MemoryKind, ...] = (),
    subject_refs: tuple[str, ...] = (),
    max_items: int = 8,
    max_estimated_tokens: int = 512,
    include_conflicted: bool = False,
    observed_from: datetime | None = None,
    observed_until: datetime | None = None,
    semantic_query: str | None = None,
) -> MemoryRetrievalQuery:
    return MemoryRetrievalQuery(
        "query:1",
        "appraisal",
        "context",
        NOW,
        memory_kinds=memory_kinds,
        subject_refs=subject_refs,
        max_items=max_items,
        max_estimated_tokens=max_estimated_tokens,
        include_conflicted=include_conflicted,
        observed_from=observed_from,
        observed_until=observed_until,
        semantic_query=semantic_query,
    )


def test_stores_valid_candidate_and_returns_immutable_evidence() -> None:
    store, _ = authority()
    result = store.write(MemoryWriteRequest(candidate()))
    view = store.retrieve(query())
    assert result.disposition is MemoryDisposition.STORE_NEW
    assert view.items[0].content.to_dict()["value"] == "game-a"
    content = view.items[0].content.to_dict()
    assert content is not view.items[0].content.to_dict()


def test_durable_candidate_requires_provenance() -> None:
    with pytest.raises(ValueError, match="provenance"):
        ValidatedMemoryCandidate(
            "candidate:bad",
            MemoryKind.SEMANTIC,
            MemoryContent("fact", "x"),
            MemoryProvenance(MemorySourceKind.TYPED_FACT, (), (), None, None, NOW),
            MemoryConfidence(0.5, "basis"),
            MemoryTemporalState(MemoryFreshnessState.FRESH),
            NOW,
        )


def test_exact_duplicate_noops_and_new_provenance_merges_without_losing_history() -> None:
    store, repository = authority()
    first = store.write(MemoryWriteRequest(candidate()))
    duplicate = store.write(MemoryWriteRequest(candidate("candidate:2")))
    merged = store.write(MemoryWriteRequest(candidate("candidate:3", source="fact:2")))
    assert first.disposition is MemoryDisposition.STORE_NEW
    assert duplicate.disposition is MemoryDisposition.NOOP_DUPLICATE
    assert merged.disposition is MemoryDisposition.MERGE_PROVENANCE
    assert len(repository.list_records()) == 1
    assert {item.source_fact_refs[0] for item in merged.record.provenance} == {"fact:1", "fact:2"}  # type: ignore[union-attr]


def test_same_immutable_provenance_with_later_observation_and_recording_is_noop() -> None:
    store, repository = authority()
    store.write(MemoryWriteRequest(candidate()))
    repeated = candidate("candidate:2")
    delayed = ValidatedMemoryCandidate(
        **{name: getattr(repeated, name) for name in repeated.__dataclass_fields__}
        | {
            "provenance": MemoryProvenance(
                repeated.provenance.source_kind,
                repeated.provenance.source_event_refs,
                repeated.provenance.source_fact_refs,
                repeated.provenance.source_memory_candidate_id,
                NOW + timedelta(minutes=1),
                NOW + timedelta(minutes=1),
            )
        }
    )
    result = store.write(MemoryWriteRequest(delayed))
    assert result.disposition is MemoryDisposition.NOOP_DUPLICATE
    assert len(repository.get("candidate:1").provenance) == 1  # type: ignore[union-attr]


def test_stale_expected_revision_is_rejected() -> None:
    store, _ = authority()
    store.write(MemoryWriteRequest(candidate()))
    result = store.write(
        MemoryWriteRequest(candidate("candidate:2", source="fact:2"), expected_revision=99)
    )
    assert result.disposition is MemoryDisposition.REJECT


def test_typed_supersession_preserves_old_record_and_unresolved_contradiction_preserves_both() -> (
    None
):
    store, repository = authority()
    old = store.write(MemoryWriteRequest(candidate()))
    superseding = store.write(
        MemoryWriteRequest(
            candidate("candidate:2", value="game-b", source="fact:2"),
            expected_revision=0,
            target_memory_id="candidate:1",
            relation_kind=MemoryRelationKind.SUPERSEDES,
        )
    )
    contradiction = store.write(
        MemoryWriteRequest(
            candidate("candidate:3", value="game-c", source="fact:3"),
            expected_revision=0,
            target_memory_id="candidate:2",
            relation_kind=MemoryRelationKind.CONTRADICTS,
        )
    )
    assert old.record is not None
    assert superseding.disposition is MemoryDisposition.SUPERSEDE
    assert repository.get("candidate:1").lifecycle is MemoryLifecycle.SUPERSEDED  # type: ignore[union-attr]
    assert contradiction.disposition is MemoryDisposition.LINK_CONTRADICTION
    assert {record.memory_id for record in repository.list_records()} == {
        "candidate:1",
        "candidate:2",
        "candidate:3",
    }
    assert store.retrieve(query(include_conflicted=True)).items[-1].memory_id in {
        "candidate:1",
        "candidate:2",
        "candidate:3",
    }


def test_related_write_rejection_never_leaves_partial_canonical_state() -> None:
    class RejectingRepository(InMemoryMemoryRepository):
        def commit_related(self, *args: object, **kwargs: object) -> bool:
            return False

    repository = RejectingRepository()
    store = MemoryStoreAuthority(repository)
    store.write(MemoryWriteRequest(candidate()))
    result = store.write(
        MemoryWriteRequest(
            candidate("candidate:2", value="game-b", source="fact:2"),
            expected_revision=0,
            target_memory_id="candidate:1",
            relation_kind=MemoryRelationKind.SUPERSEDES,
        )
    )
    assert result.disposition is MemoryDisposition.REJECT
    assert [record.memory_id for record in repository.list_records()] == ["candidate:1"]
    assert repository.list_relations() == ()


def test_similarity_hint_never_decides_duplicate_or_supersession() -> None:
    store, repository = authority()
    store.write(MemoryWriteRequest(candidate(value={"same": "nearby"})))
    result = store.write(
        MemoryWriteRequest(candidate("candidate:2", value={"same": "different"}, source="fact:2"))
    )
    assert result.disposition is MemoryDisposition.STORE_NEW
    assert len(repository.list_records()) == 2


def test_actual_claims_require_owning_typed_evidence() -> None:
    base = candidate()
    with pytest.raises(ValueError, match="Presentation"):
        ValidatedMemoryCandidate(
            **{name: getattr(base, name) for name in base.__dataclass_fields__}
            | {"claims_actual_speech": True}
        )
    with pytest.raises(ValueError, match="Actual Execution"):
        ValidatedMemoryCandidate(
            **{name: getattr(base, name) for name in base.__dataclass_fields__}
            | {"claims_executed_activity": True}
        )
    speech = candidate(source_kind=MemorySourceKind.PRESENTATION_OBSERVATION)
    assert ValidatedMemoryCandidate(
        **{name: getattr(speech, name) for name in speech.__dataclass_fields__}
        | {"claims_actual_speech": True}
    ).claims_actual_speech


def test_retrieval_is_bounded_filtered_deterministic_and_exposes_stale_conflict() -> None:
    store, _ = authority()
    store.write(
        MemoryWriteRequest(
            candidate("candidate:b", value="b", freshness=MemoryFreshnessState.STALE)
        )
    )
    store.write(
        MemoryWriteRequest(
            candidate("candidate:a", value="a", freshness=MemoryFreshnessState.FRESH)
        )
    )
    view = store.retrieve(
        query(
            memory_kinds=(MemoryKind.SEMANTIC,),
            subject_refs=("user:1",),
            max_items=1,
            max_estimated_tokens=999,
        )
    )
    assert [item.memory_id for item in view.items] == ["candidate:a"]
    assert view.truncated
    tiny = store.retrieve(query(max_items=8, max_estimated_tokens=1))
    assert tiny.items == () and tiny.truncated


def test_repository_and_index_degradation_are_typed_without_false_success() -> None:
    store, repository = authority()
    repository.available = False
    rejected = store.write(MemoryWriteRequest(candidate()))
    view = store.retrieve(query())
    assert rejected.disposition is MemoryDisposition.REJECT
    assert rejected.degradation_reasons == (MemoryDegradationReason.REPOSITORY_UNAVAILABLE,)
    assert view.degraded and view.degradation_reasons == (
        MemoryDegradationReason.REPOSITORY_UNAVAILABLE,
    )


class BrokenIndex:
    def upsert(self, record: object) -> None:
        raise RuntimeError("unavailable")

    def related_ids(self, query: str, *, limit: int) -> tuple[str, ...]:
        raise RuntimeError("unavailable")


def test_index_failure_keeps_canonical_record() -> None:
    repository = InMemoryMemoryRepository()
    store = MemoryStoreAuthority(repository, BrokenIndex())
    result = store.write(MemoryWriteRequest(candidate()))
    assert result.disposition is MemoryDisposition.STORE_NEW
    assert result.degradation_reasons == (MemoryDegradationReason.SEMANTIC_INDEX_UPDATE_FAILED,)
    assert repository.get("candidate:1") is not None


def test_semantic_index_failure_keeps_filtered_retrieval_and_reports_degradation() -> None:
    repository = InMemoryMemoryRepository()
    store = MemoryStoreAuthority(repository, BrokenIndex())
    store.write(MemoryWriteRequest(candidate("candidate:a", value="a")))
    store.write(MemoryWriteRequest(candidate("candidate:b", value="b", source="fact:2")))
    view = store.retrieve(query(semantic_query="好きなゲーム", subject_refs=("user:1",)))
    assert {item.memory_id for item in view.items} == {"candidate:a", "candidate:b"}
    assert view.degraded
    assert view.degradation_reasons == (MemoryDegradationReason.SEMANTIC_INDEX_UNAVAILABLE,)


def test_semantic_index_is_ranking_signal_not_memory_identity_authority() -> None:
    class Index:
        def upsert(self, record: object) -> None:
            pass

        def related_ids(self, query: str, *, limit: int) -> tuple[str, ...]:
            assert query == "関連"
            assert limit == 8
            return ("candidate:b",)

    repository = InMemoryMemoryRepository()
    store = MemoryStoreAuthority(repository, Index())
    store.write(MemoryWriteRequest(candidate("candidate:a", value="a")))
    store.write(
        MemoryWriteRequest(
            candidate(
                "candidate:b",
                value="b",
                source="fact:2",
                freshness=MemoryFreshnessState.STALE,
            )
        )
    )
    view = store.retrieve(query(semantic_query="関連"))
    assert [item.memory_id for item in view.items] == ["candidate:b", "candidate:a"]
    assert len(repository.list_records()) == 2


def test_retrieval_temporal_range_filters_observed_at() -> None:
    store, _ = authority()
    old = candidate("candidate:old", value="old")
    recent = candidate("candidate:recent", value="recent", source="fact:2")
    old = ValidatedMemoryCandidate(
        **{name: getattr(old, name) for name in old.__dataclass_fields__}
        | {
            "provenance": MemoryProvenance(
                old.provenance.source_kind,
                old.provenance.source_event_refs,
                old.provenance.source_fact_refs,
                old.provenance.source_memory_candidate_id,
                NOW - timedelta(days=2),
                NOW,
            ),
            "temporal": MemoryTemporalState(
                MemoryFreshnessState.HISTORICAL, observed_at=NOW - timedelta(days=2)
            ),
        }
    )
    store.write(MemoryWriteRequest(old))
    store.write(MemoryWriteRequest(recent))
    view = store.retrieve(query(observed_from=NOW - timedelta(hours=1)))
    assert [item.memory_id for item in view.items] == ["candidate:recent"]


def test_retrieval_reads_one_coherent_repository_snapshot() -> None:
    class SnapshotOnlyRepository(InMemoryMemoryRepository):
        def list_records(self) -> tuple[MemoryRecord, ...]:
            raise AssertionError("個別record読取りは禁止です")

        def list_relations(self) -> tuple[MemoryRelation, ...]:
            raise AssertionError("個別relation読取りは禁止です")

        def snapshot(self) -> MemoryRepositorySnapshot:
            return MemoryRepositorySnapshot(
                tuple(self._records[key] for key in sorted(self._records)),
                tuple(self._relations[key] for key in sorted(self._relations)),
            )

    repository = SnapshotOnlyRepository()
    store = MemoryStoreAuthority(repository)
    store.write(MemoryWriteRequest(candidate()))
    view = store.retrieve(query())
    assert [item.memory_id for item in view.items] == ["candidate:1"]


def test_temporal_filter_contract_rejects_invalid_range() -> None:
    with pytest.raises(ValueError, match="temporal range"):
        MemoryTemporalState(MemoryFreshnessState.FRESH, NOW + timedelta(seconds=1), NOW)
    with pytest.raises(ValueError, match="retrieval temporal range"):
        query(observed_from=NOW + timedelta(seconds=1), observed_until=NOW)
