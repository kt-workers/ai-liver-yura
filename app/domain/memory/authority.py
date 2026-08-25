from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from json import dumps

from app.domain.memory.contracts import (
    MemoryContent,
    MemoryDegradationReason,
    MemoryDisposition,
    MemoryEvidenceItem,
    MemoryEvidenceView,
    MemoryFreshnessState,
    MemoryLifecycle,
    MemoryRecord,
    MemoryRelation,
    MemoryRelationKind,
    MemoryRetrievalQuery,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from app.domain.memory.repository import MemoryRepositoryPort, MemorySemanticIndexPort


class MemoryStoreAuthority:
    """候補を非LLMかつ決定的に正本Memoryへ統合するAuthority。"""

    def __init__(
        self,
        repository: MemoryRepositoryPort,
        semantic_index: MemorySemanticIndexPort | None = None,
    ) -> None:
        self._repository = repository
        self._semantic_index = semantic_index

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        try:
            records = self._repository.list_records()
        except RuntimeError:
            return MemoryWriteResult(
                MemoryDisposition.REJECT,
                None,
                None,
                (MemoryDegradationReason.REPOSITORY_UNAVAILABLE,),
            )

        candidate = request.candidate
        exact = next(
            (
                record
                for record in records
                if self._identity(record.kind, record.content)
                == self._identity(candidate.memory_kind, candidate.content)
            ),
            None,
        )
        if request.target_memory_id is not None:
            target = next(
                (record for record in records if record.memory_id == request.target_memory_id), None
            )
            if target is None or request.expected_revision != target.revision:
                return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
            return self._write_related(request, target)
        if exact is not None:
            if (
                request.expected_revision is not None
                and request.expected_revision != exact.revision
            ):
                return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
            if candidate.provenance in exact.provenance:
                return MemoryWriteResult(MemoryDisposition.NOOP_DUPLICATE, exact, None)
            merged = replace(
                exact,
                revision=exact.revision + 1,
                provenance=exact.provenance + (candidate.provenance,),
                updated_at=candidate.created_at,
            )
            if not self._repository.save_record(merged, expected_revision=exact.revision):
                return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
            return self._indexed(MemoryDisposition.MERGE_PROVENANCE, merged, None)

        record = MemoryRecord(
            candidate.candidate_id,
            0,
            candidate.memory_kind,
            candidate.content,
            (candidate.provenance,),
            candidate.confidence,
            candidate.temporal,
            MemoryLifecycle.ACTIVE,
            candidate.created_at,
            candidate.created_at,
        )
        if not self._repository.save_record(record, expected_revision=None):
            return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
        return self._indexed(MemoryDisposition.STORE_NEW, record, None)

    def _write_related(
        self, request: MemoryWriteRequest, target: MemoryRecord
    ) -> MemoryWriteResult:
        candidate = request.candidate
        relation_kind = request.relation_kind
        assert relation_kind is not None
        record = MemoryRecord(
            candidate.candidate_id,
            0,
            candidate.memory_kind,
            candidate.content,
            (candidate.provenance,),
            candidate.confidence,
            candidate.temporal,
            MemoryLifecycle.ACTIVE,
            candidate.created_at,
            candidate.created_at,
        )
        if not self._repository.save_record(record, expected_revision=None):
            return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
        relation = MemoryRelation(
            f"relation:{target.memory_id}:{record.memory_id}:{relation_kind.value}",
            target.memory_id,
            record.memory_id,
            relation_kind,
            candidate.provenance.source_event_refs
            or candidate.provenance.source_fact_refs
            or (candidate.candidate_id,),
            candidate.created_at,
        )
        if not self._repository.save_relation(relation):
            return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
        if relation_kind is MemoryRelationKind.SUPERSEDES:
            superseded = replace(
                target,
                revision=target.revision + 1,
                lifecycle=MemoryLifecycle.SUPERSEDED,
                updated_at=candidate.created_at,
            )
            if not self._repository.save_record(superseded, expected_revision=target.revision):
                return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
            return self._indexed(MemoryDisposition.SUPERSEDE, record, relation)
        disposition = (
            MemoryDisposition.LINK_CONTRADICTION
            if relation_kind is MemoryRelationKind.CONTRADICTS
            else MemoryDisposition.STORE_NEW
        )
        return self._indexed(disposition, record, relation)

    def retrieve(self, query: MemoryRetrievalQuery) -> MemoryEvidenceView:
        try:
            records = self._repository.list_records()
            relations = self._repository.list_relations()
        except RuntimeError:
            return MemoryEvidenceView(
                query.query_id,
                query.created_at,
                (),
                False,
                True,
                (MemoryDegradationReason.REPOSITORY_UNAVAILABLE,),
            )
        conflicting: dict[str, tuple[str, ...]] = {}
        for relation in relations:
            if relation.kind is MemoryRelationKind.CONTRADICTS:
                conflicting[relation.left_memory_id] = conflicting.get(
                    relation.left_memory_id, ()
                ) + (relation.right_memory_id,)
                conflicting[relation.right_memory_id] = conflicting.get(
                    relation.right_memory_id, ()
                ) + (relation.left_memory_id,)
        filtered = [record for record in records if self._matches(record, query, conflicting)]
        ranked = sorted(filtered, key=lambda record: (-self._score(record), record.memory_id))
        items: list[MemoryEvidenceItem] = []
        tokens = 0
        truncated = False
        for record in ranked:
            estimate = self._estimate_tokens(record.content)
            if len(items) >= query.max_items or tokens + estimate > query.max_estimated_tokens:
                truncated = True
                continue
            items.append(
                MemoryEvidenceItem(
                    record.memory_id,
                    record.kind,
                    record.content,
                    record.provenance,
                    record.confidence,
                    record.temporal,
                    record.lifecycle,
                    conflicting.get(record.memory_id, ()),
                    estimate,
                    self._score(record),
                )
            )
            tokens += estimate
        return MemoryEvidenceView(query.query_id, query.created_at, tuple(items), truncated, False)

    def _indexed(
        self, disposition: MemoryDisposition, record: MemoryRecord, relation: MemoryRelation | None
    ) -> MemoryWriteResult:
        if self._semantic_index is None:
            return MemoryWriteResult(disposition, record, relation)
        try:
            self._semantic_index.upsert(record)
        except RuntimeError:
            return MemoryWriteResult(
                disposition,
                record,
                relation,
                (MemoryDegradationReason.SEMANTIC_INDEX_UPDATE_FAILED,),
            )
        return MemoryWriteResult(disposition, record, relation)

    @staticmethod
    def _identity(kind: object, content: MemoryContent) -> str:
        payload = dumps(
            {"kind": getattr(kind, "value", kind), **content.to_dict()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode()).hexdigest()

    @staticmethod
    def _matches(
        record: MemoryRecord, query: MemoryRetrievalQuery, conflicts: dict[str, tuple[str, ...]]
    ) -> bool:
        if query.memory_kinds and record.kind not in query.memory_kinds:
            return False
        if query.subject_refs and record.content.subject_ref not in query.subject_refs:
            return False
        if (
            query.temporal_scope_ref is not None
            and record.content.temporal_scope_ref != query.temporal_scope_ref
        ):
            return False
        if record.lifecycle is MemoryLifecycle.ARCHIVED:
            return False
        return query.include_conflicted or record.memory_id not in conflicts

    @staticmethod
    def _score(record: MemoryRecord) -> float:
        freshness = {
            MemoryFreshnessState.FRESH: 0.2,
            MemoryFreshnessState.STALE: 0.1,
            MemoryFreshnessState.HISTORICAL: 0.0,
        }[record.temporal.freshness]
        lifecycle = 0.1 if record.lifecycle is MemoryLifecycle.ACTIVE else 0.0
        return record.confidence.value + freshness + lifecycle

    @staticmethod
    def _estimate_tokens(content: MemoryContent) -> int:
        raw = dumps(content.to_dict(), ensure_ascii=False, sort_keys=True, default=str)
        return max(1, (len(raw) + 3) // 4)
