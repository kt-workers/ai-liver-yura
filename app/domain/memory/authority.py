from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from json import dumps

from app.domain.contracts.common import utc_instant
from app.domain.memory.contracts import (
    MemoryContent,
    MemoryDegradationReason,
    MemoryDisposition,
    MemoryEvidenceItem,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryRecord,
    MemoryRelation,
    MemoryRelationKind,
    MemoryRetrievalQuery,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from app.domain.memory.ranking import (
    MemoryRankingMissingBehavior,
    MemoryRankingPolarity,
    MemoryRankingSignal,
    MemoryRetrievalDiagnostic,
    MemoryRetrievalDiagnosticCode,
    MemoryRetrievalError,
    MemoryRetrievalFailureCode,
    MemoryRetrievalRankingPolicy,
    MemorySemanticRelevance,
    RankedMemoryEvidenceView,
)
from app.domain.memory.repository import MemoryRepositoryPort, MemorySemanticIndexPort


class MemoryStoreAuthority:
    """候補を非LLMかつ決定的に正本Memoryへ統合するAuthority。"""

    def __init__(
        self,
        repository: MemoryRepositoryPort,
        semantic_index: MemorySemanticIndexPort | None = None,
        *,
        ranking_policy: MemoryRetrievalRankingPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._semantic_index = semantic_index
        self._ranking_policy = ranking_policy

    @property
    def retrieval_ranking_policy(self) -> MemoryRetrievalRankingPolicy | None:
        return self._ranking_policy

    def update_retrieval_ranking_policy(self, policy: MemoryRetrievalRankingPolicy) -> None:
        if not isinstance(policy, MemoryRetrievalRankingPolicy):
            raise ValueError("Memory retrieval ranking policy が必要です")
        self._ranking_policy = policy

    def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        try:
            records = self._repository.snapshot().records
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
            if any(
                self._provenance_identity(candidate.provenance)
                == self._provenance_identity(provenance)
                for provenance in exact.provenance
            ):
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
        superseded: MemoryRecord | None = None
        if relation_kind is MemoryRelationKind.SUPERSEDES:
            superseded = replace(
                target,
                revision=target.revision + 1,
                lifecycle=MemoryLifecycle.SUPERSEDED,
                updated_at=candidate.created_at,
            )
        if not self._repository.commit_related(
            record,
            relation,
            target_update=superseded,
            expected_target_revision=target.revision if superseded is not None else None,
        ):
            return MemoryWriteResult(MemoryDisposition.REJECT, None, None)
        if superseded is not None:
            return self._indexed(MemoryDisposition.SUPERSEDE, record, relation)
        disposition = (
            MemoryDisposition.LINK_CONTRADICTION
            if relation_kind is MemoryRelationKind.CONTRADICTS
            else MemoryDisposition.STORE_NEW
        )
        return self._indexed(disposition, record, relation)

    def retrieve(self, query: MemoryRetrievalQuery) -> RankedMemoryEvidenceView:
        policy = self._require_ranking_policy()
        try:
            snapshot = self._repository.snapshot()
        except RuntimeError:
            return self._view(
                query,
                policy,
                (),
                False,
                (MemoryDegradationReason.REPOSITORY_UNAVAILABLE,),
                (),
            )

        conflicting: dict[str, tuple[str, ...]] = {}
        for relation in snapshot.relations:
            if relation.kind is MemoryRelationKind.CONTRADICTS:
                conflicting[relation.left_memory_id] = conflicting.get(
                    relation.left_memory_id, ()
                ) + (relation.right_memory_id,)
                conflicting[relation.right_memory_id] = conflicting.get(
                    relation.right_memory_id, ()
                ) + (relation.left_memory_id,)

        semantic_scores, reasons = self._semantic_scores(query)
        self._assert_policy_current(policy)
        filtered = [
            record
            for record in snapshot.records
            if self._matches(record, query, conflicting)
        ]
        ranked: list[tuple[MemoryRecord, float, datetime]] = []
        diagnostics: list[MemoryRetrievalDiagnostic] = []
        for record in filtered:
            rank = self._rank_record(record, query, policy, semantic_scores)
            if rank is None:
                diagnostics.append(
                    MemoryRetrievalDiagnostic(
                        MemoryRetrievalDiagnosticCode.INVALID_RECORD_TIME,
                        record.memory_id,
                    )
                )
                continue
            score, reference_time = rank
            if score is None:
                diagnostics.append(
                    MemoryRetrievalDiagnostic(
                        MemoryRetrievalDiagnosticCode.UNRANKABLE_ZERO_DENOMINATOR,
                        record.memory_id,
                    )
                )
                continue
            ranked.append((record, score, reference_time))
        ranked.sort(
            key=lambda item: (
                -item[1],
                -utc_instant(item[2]).timestamp(),
                item[0].memory_id,
            )
        )

        envelope_tokens = self._estimate_tokens(
            {
                "query_id": query.query_id,
                "generated_at": query.created_at.isoformat(),
                "ranking_policy_id": policy.policy_id,
                "ranking_policy_revision": policy.policy_revision,
                "token_estimator_id": policy.token_estimator_id,
                "token_estimator_revision": policy.token_estimator_revision,
                "degradation_reasons": [reason.value for reason in reasons],
                "diagnostics": [
                    {"code": item.code.value, "memory_id": item.memory_id}
                    for item in diagnostics
                ],
            }
        )
        items: list[MemoryEvidenceItem] = []
        tokens = envelope_tokens
        truncated = False
        for record, score, _ in ranked:
            if len(items) >= query.max_items:
                truncated = True
                break
            estimate = self._estimate_tokens(self._evidence_payload(record, conflicting, score))
            if tokens + estimate > query.max_estimated_tokens:
                truncated = True
                break
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
                    score,
                )
            )
            tokens += estimate
        self._assert_policy_current(policy)
        return self._view(
            query,
            policy,
            tuple(items),
            truncated,
            reasons,
            tuple(diagnostics),
        )

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
    def _provenance_identity(provenance: object) -> tuple[object, ...]:
        if not isinstance(provenance, MemoryProvenance):
            raise ValueError("provenance が不正です")
        return (
            provenance.source_kind,
            provenance.source_event_refs,
            provenance.source_fact_refs,
            provenance.source_memory_candidate_id,
        )

    def _semantic_scores(
        self, query: MemoryRetrievalQuery
    ) -> tuple[dict[str, float], tuple[MemoryDegradationReason, ...]]:
        if query.semantic_query is None:
            return {}, ()
        if self._semantic_index is None:
            return {}, (MemoryDegradationReason.SEMANTIC_INDEX_UNAVAILABLE,)
        try:
            related = tuple(
                self._semantic_index.related_scores(
                    query.semantic_query,
                    limit=query.max_items,
                )
            )
        except RuntimeError:
            return {}, (MemoryDegradationReason.SEMANTIC_INDEX_UNAVAILABLE,)
        if any(not isinstance(item, MemorySemanticRelevance) for item in related):
            raise MemoryRetrievalError(
                MemoryRetrievalFailureCode.INVALID_SEMANTIC_SCORE,
                "semantic indexがtyped normalized relevanceを返しませんでした",
            )
        if len({item.memory_id for item in related}) != len(related):
            raise MemoryRetrievalError(
                MemoryRetrievalFailureCode.INVALID_SEMANTIC_SCORE,
                "semantic relevance memory_idが重複しています",
            )
        return {item.memory_id: item.score for item in related}, ()

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
        observed_at = record.temporal.observed_at
        if query.observed_from is not None and (
            observed_at is None or observed_at < query.observed_from
        ):
            return False
        if query.observed_until is not None and (
            observed_at is None or observed_at > query.observed_until
        ):
            return False
        if record.lifecycle is MemoryLifecycle.ARCHIVED:
            return False
        return query.include_conflicted or record.memory_id not in conflicts

    def _rank_record(
        self,
        record: MemoryRecord,
        query: MemoryRetrievalQuery,
        policy: MemoryRetrievalRankingPolicy,
        semantic_scores: dict[str, float],
    ) -> tuple[float | None, datetime] | None:
        reference_time = self._reference_time(record)
        age_seconds = (
            utc_instant(query.created_at) - utc_instant(reference_time)
        ).total_seconds()
        if age_seconds < 0:
            return None
        numerator = 0.0
        denominator = 0.0
        for rule in policy.signal_rules:
            if rule.weight == 0:
                continue
            value = self._signal_value(
                rule.signal,
                record,
                age_seconds,
                policy,
                semantic_scores,
            )
            if value is None:
                if rule.missing_behavior is MemoryRankingMissingBehavior.ZERO:
                    denominator += rule.weight
                    continue
                if rule.missing_behavior is MemoryRankingMissingBehavior.EXCLUDE:
                    continue
                raise MemoryRetrievalError(
                    MemoryRetrievalFailureCode.REQUIRED_SIGNAL_MISSING,
                    f"{record.memory_id}: {rule.signal.value}",
                )
            signed = (
                value
                if rule.polarity is MemoryRankingPolarity.POSITIVE
                else 1.0 - value
            )
            numerator += rule.weight * signed
            denominator += rule.weight
        if denominator == 0:
            return None, reference_time
        score = numerator / denominator
        if not 0 <= score <= 1:
            raise MemoryRetrievalError(
                MemoryRetrievalFailureCode.INVALID_SEMANTIC_SCORE,
                f"ranking score out of range: {record.memory_id}",
            )
        return score, reference_time

    @staticmethod
    def _signal_value(
        signal: MemoryRankingSignal,
        record: MemoryRecord,
        age_seconds: float,
        policy: MemoryRetrievalRankingPolicy,
        semantic_scores: dict[str, float],
    ) -> float | None:
        if signal is MemoryRankingSignal.SEMANTIC_RELEVANCE:
            return semantic_scores.get(record.memory_id)
        if signal is MemoryRankingSignal.RECENCY:
            return 2 ** (-age_seconds / policy.recency_half_life_seconds)
        if signal is MemoryRankingSignal.CONFIDENCE:
            return record.confidence.value
        if signal is MemoryRankingSignal.FRESHNESS:
            return policy.freshness_score(record.temporal.freshness)
        return None

    @staticmethod
    def _reference_time(record: MemoryRecord) -> datetime:
        if record.temporal.observed_at is not None:
            return record.temporal.observed_at
        if record.provenance:
            return max(item.recorded_at for item in record.provenance)
        return record.created_at

    @staticmethod
    def _estimate_tokens(payload: object) -> int:
        raw = dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return max(1, (len(raw) + 2) // 3)

    @staticmethod
    def _evidence_payload(
        record: MemoryRecord,
        conflicts: dict[str, tuple[str, ...]],
        score: float,
    ) -> dict[str, object]:
        return {
            "memory_id": record.memory_id,
            "kind": record.kind.value,
            "content": record.content.to_dict(),
            "provenance": [item.to_dict() for item in record.provenance],
            "confidence": {
                "value": record.confidence.value,
                "basis": record.confidence.basis,
            },
            "temporal": {
                "freshness": record.temporal.freshness.value,
                "valid_from": (
                    None
                    if record.temporal.valid_from is None
                    else record.temporal.valid_from.isoformat()
                ),
                "valid_until": (
                    None
                    if record.temporal.valid_until is None
                    else record.temporal.valid_until.isoformat()
                ),
                "observed_at": (
                    None
                    if record.temporal.observed_at is None
                    else record.temporal.observed_at.isoformat()
                ),
            },
            "lifecycle": record.lifecycle.value,
            "contradiction_refs": list(conflicts.get(record.memory_id, ())),
            "score": score,
        }

    def _require_ranking_policy(self) -> MemoryRetrievalRankingPolicy:
        policy = self._ranking_policy
        if policy is None:
            raise MemoryRetrievalError(
                MemoryRetrievalFailureCode.POLICY_MISSING,
                "Memory retrieval ranking policyが設定されていません",
            )
        return policy

    def _assert_policy_current(self, expected: MemoryRetrievalRankingPolicy) -> None:
        current = self._ranking_policy
        if current is None or not current.same_generation(
            expected.policy_id,
            expected.policy_revision,
        ):
            raise MemoryRetrievalError(
                MemoryRetrievalFailureCode.POLICY_STALE,
                "retrieval中にMemory ranking policy generationが変更されました",
            )

    @staticmethod
    def _view(
        query: MemoryRetrievalQuery,
        policy: MemoryRetrievalRankingPolicy,
        items: tuple[MemoryEvidenceItem, ...],
        truncated: bool,
        reasons: tuple[MemoryDegradationReason, ...],
        diagnostics: tuple[MemoryRetrievalDiagnostic, ...],
    ) -> RankedMemoryEvidenceView:
        return RankedMemoryEvidenceView(
            query_id=query.query_id,
            generated_at=query.created_at,
            items=items,
            truncated=truncated,
            degraded=bool(reasons),
            degradation_reasons=reasons,
            ranking_policy_id=policy.policy_id,
            ranking_policy_revision=policy.policy_revision,
            token_estimator_id=policy.token_estimator_id,
            token_estimator_revision=policy.token_estimator_revision,
            diagnostics=diagnostics,
        )
