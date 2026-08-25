from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import TypeVar, cast

from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
)


class MemoryKind(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"
    PREFERENCE = "preference"
    ACTIVITY_SKILL = "activity_skill"


class MemoryLifecycle(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class MemoryFreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    HISTORICAL = "historical"


class MemoryRelationKind(str, Enum):
    SUPPORTS = "supports"
    REFINES = "refines"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"


class MemoryDisposition(str, Enum):
    STORE_NEW = "store_new"
    NOOP_DUPLICATE = "noop_duplicate"
    MERGE_PROVENANCE = "merge_provenance"
    SUPERSEDE = "supersede"
    LINK_CONTRADICTION = "link_contradiction"
    REJECT = "reject"


class MemorySourceKind(str, Enum):
    TYPED_EVENT = "typed_event"
    TYPED_FACT = "typed_fact"
    REFLECTION_CANDIDATE = "reflection_candidate"
    PRESENTATION_OBSERVATION = "presentation_observation"
    ACTUAL_EXECUTION_FACT = "actual_execution_fact"
    PREPARED_CANDIDATE = "prepared_candidate"
    PLAN = "plan"


class MemoryDegradationReason(str, Enum):
    REPOSITORY_UNAVAILABLE = "repository_unavailable"
    SEMANTIC_INDEX_UNAVAILABLE = "semantic_index_unavailable"
    SEMANTIC_INDEX_UPDATE_FAILED = "semantic_index_update_failed"


T = TypeVar("T")


def _items(values: object, typ: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{name} が配列ではありません")
    result = tuple(values)
    if any(not isinstance(item, typ) for item in result):
        raise ValueError(f"{name} が不正です")
    return cast(tuple[T, ...], result)


def _ids(values: object, name: str, *, required: bool = False) -> tuple[str, ...]:
    result = _items(values, str, name)
    if required and not result:
        raise ValueError(f"{name} は空にできません")
    if any(not item.strip() for item in result) or len(set(result)) != len(result):
        raise ValueError(f"{name} が不正です")
    return result


@dataclass(frozen=True, slots=True)
class MemoryContent:
    predicate: str
    value: JsonValue
    subject_ref: str | None = None
    temporal_scope_ref: str | None = None
    qualifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.predicate, "predicate")
        if self.subject_ref is not None:
            require_identifier(self.subject_ref, "subject_ref")
        if self.temporal_scope_ref is not None:
            require_identifier(self.temporal_scope_ref, "temporal_scope_ref")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "qualifiers", _ids(self.qualifiers, "qualifiers"))

    def to_dict(self) -> dict[str, object]:
        return {
            "predicate": self.predicate,
            "value": thaw_json(self.value),
            "subject_ref": self.subject_ref,
            "temporal_scope_ref": self.temporal_scope_ref,
            "qualifiers": list(self.qualifiers),
        }


@dataclass(frozen=True, slots=True)
class MemoryProvenance:
    source_kind: MemorySourceKind
    source_event_refs: tuple[str, ...]
    source_fact_refs: tuple[str, ...]
    source_memory_candidate_id: str | None
    observed_at: datetime | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, MemorySourceKind):
            raise ValueError("source_kind が不正です")
        object.__setattr__(
            self, "source_event_refs", _ids(self.source_event_refs, "source_event_refs")
        )
        object.__setattr__(
            self, "source_fact_refs", _ids(self.source_fact_refs, "source_fact_refs")
        )
        if self.source_memory_candidate_id is not None:
            require_identifier(self.source_memory_candidate_id, "source_memory_candidate_id")
        if self.observed_at is not None:
            require_aware(self.observed_at, "observed_at")
        require_aware(self.recorded_at, "recorded_at")

    @property
    def has_evidence(self) -> bool:
        return bool(
            self.source_event_refs or self.source_fact_refs or self.source_memory_candidate_id
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind.value,
            "source_event_refs": list(self.source_event_refs),
            "source_fact_refs": list(self.source_fact_refs),
            "source_memory_candidate_id": self.source_memory_candidate_id,
            "observed_at": None if self.observed_at is None else self.observed_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class MemoryConfidence:
    value: float
    basis: str

    def __post_init__(self) -> None:
        if (
            type(self.value) not in (int, float)
            or not isfinite(self.value)
            or not 0 <= self.value <= 1
        ):
            raise ValueError("confidence が不正です")
        object.__setattr__(self, "value", float(self.value))
        require_identifier(self.basis, "basis")


@dataclass(frozen=True, slots=True)
class MemoryTemporalState:
    freshness: MemoryFreshnessState
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.freshness, MemoryFreshnessState):
            raise ValueError("freshness が不正です")
        for name in ("valid_from", "valid_until", "observed_at"):
            value = getattr(self, name)
            if value is not None:
                require_aware(value, name)
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from > self.valid_until
        ):
            raise ValueError("temporal range が不正です")


@dataclass(frozen=True, slots=True)
class ValidatedMemoryCandidate:
    candidate_id: str
    memory_kind: MemoryKind
    content: MemoryContent
    provenance: MemoryProvenance
    confidence: MemoryConfidence
    temporal: MemoryTemporalState
    created_at: datetime
    importance_hint: float | None = None
    suggested_related_memory_ids: tuple[str, ...] = ()
    source_context_revision: int | None = None
    claims_actual_speech: bool = False
    claims_executed_activity: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.candidate_id, "candidate_id")
        if not isinstance(self.memory_kind, MemoryKind) or not isinstance(
            self.content, MemoryContent
        ):
            raise ValueError("memory candidate が不正です")
        if (
            not isinstance(self.provenance, MemoryProvenance)
            or not isinstance(self.confidence, MemoryConfidence)
            or not isinstance(self.temporal, MemoryTemporalState)
        ):
            raise ValueError("memory candidate metadata が不正です")
        require_aware(self.created_at, "created_at")
        if self.importance_hint is not None:
            if (
                type(self.importance_hint) not in (int, float)
                or not isfinite(self.importance_hint)
                or not 0 <= self.importance_hint <= 1
            ):
                raise ValueError("importance_hint が不正です")
            object.__setattr__(self, "importance_hint", float(self.importance_hint))
        object.__setattr__(
            self,
            "suggested_related_memory_ids",
            _ids(self.suggested_related_memory_ids, "suggested_related_memory_ids"),
        )
        require_revision(self.source_context_revision, "source_context_revision", optional=True)
        if (
            type(self.claims_actual_speech) is not bool
            or type(self.claims_executed_activity) is not bool
        ):
            raise ValueError("actual claim が不正です")
        if self.memory_kind is not MemoryKind.WORKING and not self.provenance.has_evidence:
            raise ValueError("durable Memoryにはprovenanceが必要です")
        if (
            self.claims_actual_speech
            and self.provenance.source_kind is not MemorySourceKind.PRESENTATION_OBSERVATION
        ):
            raise ValueError("actual speechにはPresentation evidenceが必要です")
        if (
            self.claims_executed_activity
            and self.provenance.source_kind is not MemorySourceKind.ACTUAL_EXECUTION_FACT
        ):
            raise ValueError("executed activityにはActual Execution Factが必要です")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    revision: int
    kind: MemoryKind
    content: MemoryContent
    provenance: tuple[MemoryProvenance, ...]
    confidence: MemoryConfidence
    temporal: MemoryTemporalState
    lifecycle: MemoryLifecycle
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.memory_id, "memory_id")
        require_revision(self.revision, "revision")
        if not isinstance(self.kind, MemoryKind) or not isinstance(self.content, MemoryContent):
            raise ValueError("memory record が不正です")
        provenance = _items(self.provenance, MemoryProvenance, "provenance")
        if self.kind is not MemoryKind.WORKING and not provenance:
            raise ValueError("durable Memory recordにはprovenanceが必要です")
        if (
            not isinstance(self.confidence, MemoryConfidence)
            or not isinstance(self.temporal, MemoryTemporalState)
            or not isinstance(self.lifecycle, MemoryLifecycle)
        ):
            raise ValueError("memory record metadata が不正です")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at が不正です")
        object.__setattr__(self, "provenance", provenance)


@dataclass(frozen=True, slots=True)
class MemoryRelation:
    relation_id: str
    left_memory_id: str
    right_memory_id: str
    kind: MemoryRelationKind
    evidence_refs: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("relation_id", "left_memory_id", "right_memory_id"):
            require_identifier(getattr(self, name), name)
        if self.left_memory_id == self.right_memory_id or not isinstance(
            self.kind, MemoryRelationKind
        ):
            raise ValueError("memory relation が不正です")
        object.__setattr__(
            self, "evidence_refs", _ids(self.evidence_refs, "evidence_refs", required=True)
        )
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class MemoryWriteRequest:
    candidate: ValidatedMemoryCandidate
    expected_revision: int | None = None
    target_memory_id: str | None = None
    relation_kind: MemoryRelationKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, ValidatedMemoryCandidate):
            raise ValueError("memory candidate が不正です")
        require_revision(self.expected_revision, "expected_revision", optional=True)
        if self.target_memory_id is not None:
            require_identifier(self.target_memory_id, "target_memory_id")
        if self.relation_kind is not None and not isinstance(
            self.relation_kind, MemoryRelationKind
        ):
            raise ValueError("relation_kind が不正です")
        if (self.target_memory_id is None) != (self.relation_kind is None):
            raise ValueError("target/relation 指定が不正です")


@dataclass(frozen=True, slots=True)
class MemoryWriteResult:
    disposition: MemoryDisposition
    record: MemoryRecord | None
    relation: MemoryRelation | None
    degradation_reasons: tuple[MemoryDegradationReason, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, MemoryDisposition):
            raise ValueError("disposition が不正です")
        if self.record is not None and not isinstance(self.record, MemoryRecord):
            raise ValueError("record が不正です")
        if self.relation is not None and not isinstance(self.relation, MemoryRelation):
            raise ValueError("relation が不正です")
        reasons = _items(self.degradation_reasons, MemoryDegradationReason, "degradation_reasons")
        if len(set(reasons)) != len(reasons):
            raise ValueError("degradation_reasons が重複しています")
        object.__setattr__(self, "degradation_reasons", reasons)


@dataclass(frozen=True, slots=True)
class MemoryRetrievalQuery:
    query_id: str
    requester: str
    purpose: str
    created_at: datetime
    memory_kinds: tuple[MemoryKind, ...] = ()
    subject_refs: tuple[str, ...] = ()
    temporal_scope_ref: str | None = None
    max_items: int = 8
    max_estimated_tokens: int = 512
    include_conflicted: bool = False

    def __post_init__(self) -> None:
        for name in ("query_id", "requester", "purpose"):
            require_identifier(getattr(self, name), name)
        require_aware(self.created_at, "created_at")
        kinds = _items(self.memory_kinds, MemoryKind, "memory_kinds")
        if len(set(kinds)) != len(kinds):
            raise ValueError("memory_kinds が重複しています")
        object.__setattr__(self, "memory_kinds", kinds)
        object.__setattr__(self, "subject_refs", _ids(self.subject_refs, "subject_refs"))
        if self.temporal_scope_ref is not None:
            require_identifier(self.temporal_scope_ref, "temporal_scope_ref")
        if (
            type(self.max_items) is not int
            or self.max_items < 1
            or type(self.max_estimated_tokens) is not int
            or self.max_estimated_tokens < 1
            or type(self.include_conflicted) is not bool
        ):
            raise ValueError("retrieval bounds が不正です")


@dataclass(frozen=True, slots=True)
class MemoryEvidenceItem:
    memory_id: str
    kind: MemoryKind
    content: MemoryContent
    provenance: tuple[MemoryProvenance, ...]
    confidence: MemoryConfidence
    temporal: MemoryTemporalState
    lifecycle: MemoryLifecycle
    contradiction_refs: tuple[str, ...]
    estimated_tokens: int
    score: float

    def __post_init__(self) -> None:
        require_identifier(self.memory_id, "memory_id")
        if (
            not isinstance(self.kind, MemoryKind)
            or not isinstance(self.content, MemoryContent)
            or not isinstance(self.confidence, MemoryConfidence)
            or not isinstance(self.temporal, MemoryTemporalState)
            or not isinstance(self.lifecycle, MemoryLifecycle)
        ):
            raise ValueError("memory evidence が不正です")
        object.__setattr__(
            self, "provenance", _items(self.provenance, MemoryProvenance, "provenance")
        )
        object.__setattr__(
            self, "contradiction_refs", _ids(self.contradiction_refs, "contradiction_refs")
        )
        if (
            type(self.estimated_tokens) is not int
            or self.estimated_tokens < 1
            or type(self.score) not in (int, float)
            or not isfinite(self.score)
        ):
            raise ValueError("memory evidence ranking が不正です")
        object.__setattr__(self, "score", float(self.score))


@dataclass(frozen=True, slots=True)
class MemoryEvidenceView:
    query_id: str
    generated_at: datetime
    items: tuple[MemoryEvidenceItem, ...]
    truncated: bool
    degraded: bool
    degradation_reasons: tuple[MemoryDegradationReason, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.query_id, "query_id")
        require_aware(self.generated_at, "generated_at")
        items = _items(self.items, MemoryEvidenceItem, "items")
        if (
            len({item.memory_id for item in items}) != len(items)
            or type(self.truncated) is not bool
            or type(self.degraded) is not bool
        ):
            raise ValueError("memory evidence view が不正です")
        reasons = _items(self.degradation_reasons, MemoryDegradationReason, "degradation_reasons")
        if self.degraded != bool(reasons) or len(set(reasons)) != len(reasons):
            raise ValueError("degradation state が不正です")
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "degradation_reasons", reasons)
