"""#364のimmutable Reflection contracts。"""

from __future__ import annotations

from collections.abc import Mapping
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
from app.domain.memory.contracts import (
    MemoryConfidence,
    MemoryContent,
    MemoryKind,
    MemoryProvenance,
    MemoryRelationKind,
    MemorySourceKind,
    MemoryTemporalState,
    ValidatedMemoryCandidate,
)
from app.domain.memory.ranking import estimate_memory_token_units


class ReflectionSourceKind(str, Enum):
    INPUT_MEANING = "input_meaning"
    PRESENTATION_FACT = "presentation_fact"
    EXECUTION_FACT = "execution_fact"
    ACTIVITY_RESULT = "activity_result"
    INTERNAL_STATE_TRANSITION = "internal_state_transition"
    RELATIONSHIP_TRANSITION = "relationship_transition"
    GOAL_TRANSITION = "goal_transition"
    GAME_RESULT = "game_result"
    STREAMING_RESULT = "streaming_result"
    MEMORY_EVIDENCE = "memory_evidence"
    LIFECYCLE_EVENT = "lifecycle_event"


class ReflectionTriggerKind(str, Enum):
    EPISODE_COMPLETED = "episode_completed"
    ACTIVITY_COMPLETED = "activity_completed"
    SESSION_COMPLETED = "session_completed"
    RELATIONSHIP_RELEVANT_CHANGE = "relationship_relevant_change"
    SIGNIFICANT_STATE_TRANSITION = "significant_state_transition"
    IDLE_CONSOLIDATION = "idle_consolidation"
    BATCH_THRESHOLD = "batch_threshold"
    SCHEDULED_LOW_PRIORITY = "scheduled_low_priority"


class ReflectionSupportRelation(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    AMBIGUOUS = "ambiguous"


class ReflectionCandidateStatus(str, Enum):
    ACCEPTED_FOR_STORE_SUBMISSION = "accepted_for_store_submission"
    REJECTED_UNSUPPORTED = "rejected_unsupported"
    REJECTED_AMBIGUOUS = "rejected_ambiguous"
    REJECTED_CONTRADICTED = "rejected_contradicted"
    REJECTED_INVALID_PROVENANCE = "rejected_invalid_provenance"
    REJECTED_STALE = "rejected_stale"
    REJECTED_POLICY = "rejected_policy"
    DEFERRED_QUEUE_PRESSURE = "deferred_queue_pressure"
    REFLECTION_PROVIDER_UNAVAILABLE = "reflection_provider_unavailable"
    SUPPORT_PROVIDER_UNAVAILABLE = "support_provider_unavailable"
    STORE_UNAVAILABLE = "store_unavailable"


class ReflectionEventKind(str, Enum):
    TRIGGERED = "reflection_triggered"
    COALESCED = "reflection_coalesced"
    CANCELLED = "reflection_cancelled"
    DEFERRED = "reflection_deferred"
    CONTEXT_CAPTURED = "reflection_context_captured"
    PROPOSAL_STARTED = "reflection_proposal_started"
    PROPOSAL_COMPLETED = "reflection_proposal_completed"
    PROPOSAL_FAILED = "reflection_proposal_failed"
    SUPPORT_STARTED = "reflection_support_started"
    SUPPORT_COMPLETED = "reflection_support_completed"
    SUPPORT_FAILED = "reflection_support_failed"
    CANDIDATE_ACCEPTED = "reflection_candidate_accepted"
    CANDIDATE_REJECTED = "reflection_candidate_rejected"


class ReflectionPersistenceHint(str, Enum):
    TRANSIENT = "transient"
    SHORT = "short"
    DURABLE = "durable"


T = TypeVar("T")


def _owned(
    values: object,
    typ: type[T],
    name: str,
    *,
    maximum: int | None = None,
) -> tuple[T, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{name}は配列である必要があります")
    result = tuple(values)
    if maximum is not None and len(result) > maximum:
        raise ValueError(f"{name}が不正です")
    if any(not isinstance(value, typ) for value in result):
        raise ValueError(f"{name}が不正です")
    return cast(tuple[T, ...], result)


def _identifiers(
    values: object,
    name: str,
    *,
    maximum: int | None = None,
) -> tuple[str, ...]:
    result = _owned(values, str, name, maximum=maximum)
    if len(set(result)) != len(result) or any(not value.strip() for value in result):
        raise ValueError(f"{name}が不正です")
    return result


def _unit(value: object, name: str) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"{name}は[0, 1]の有限値である必要があります")
    numeric = float(cast(int | float, value))
    if not isfinite(numeric) or not 0 <= numeric <= 1:
        raise ValueError(f"{name}は[0, 1]の有限値である必要があります")
    return numeric


def _bounded_payload(value: object, name: str, *, maximum_bytes: int = 16_384) -> JsonValue:
    try:
        _validate_bounded_json(value, name)
        frozen = freeze_json(value)
        rendered = repr(thaw_json(frozen)).encode("utf-8")
    except RecursionError as error:
        raise ValueError(f"{name}が許容depthを超えています") from error
    if len(rendered) > maximum_bytes:
        raise ValueError(f"{name}が許容sizeを超えています")
    return frozen


def _validate_bounded_json(value: object, name: str, *, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError(f"{name}が許容depthを超えています")
    if value is None or type(value) in {str, bool, int, float}:
        if isinstance(value, str) and len(value) > 4_096:
            raise ValueError(f"{name}の文字列が許容sizeを超えています")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError(f"{name}に有限でない数値を含められません")
        return
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError(f"{name}のobject item数が許容sizeを超えています")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError(f"{name}のobject keyが不正です")
            _validate_bounded_json(item, name, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ValueError(f"{name}のarray item数が許容sizeを超えています")
        for item in value:
            _validate_bounded_json(item, name, depth=depth + 1)
        return
    raise ValueError(f"{name}のJSON値が不正です")


@dataclass(frozen=True, slots=True)
class ReflectionSourceEvidence:
    source_ref: str
    source_kind: ReflectionSourceKind
    owner: str
    source_revision: int | None
    occurred_at: datetime
    semantic_payload: JsonValue
    provenance_refs: tuple[str, ...]
    confidence: float | None = None
    retracted: bool = False
    source_excerpt: str | None = None
    source_excerpt_truncated: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.source_ref, "source_ref")
        if not isinstance(self.source_kind, ReflectionSourceKind):
            raise ValueError("source_kindが不正です")
        require_identifier(self.owner, "owner")
        require_revision(self.source_revision, "source_revision", optional=True)
        require_aware(self.occurred_at, "occurred_at")
        object.__setattr__(
            self,
            "semantic_payload",
            _bounded_payload(self.semantic_payload, "semantic_payload"),
        )
        object.__setattr__(
            self,
            "provenance_refs",
            _identifiers(self.provenance_refs, "provenance_refs"),
        )
        if self.confidence is not None:
            object.__setattr__(self, "confidence", _unit(self.confidence, "confidence"))
        if type(self.retracted) is not bool:
            raise ValueError("retractedが不正です")
        if self.source_excerpt is not None and not isinstance(self.source_excerpt, str):
            raise ValueError("source_excerptが不正です")
        if type(self.source_excerpt_truncated) is not bool:
            raise ValueError("source_excerpt_truncatedが不正です")
        if self.source_excerpt is None and self.source_excerpt_truncated:
            raise ValueError("excerpt無しでtruncatedにできません")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "source_kind": self.source_kind.value,
            "owner": self.owner,
            "source_revision": self.source_revision,
            "occurred_at": self.occurred_at.isoformat(),
            "semantic_payload": thaw_json(self.semantic_payload),
            "provenance_refs": list(self.provenance_refs),
            "confidence": self.confidence,
            "retracted": self.retracted,
            "source_excerpt": self.source_excerpt,
            "source_excerpt_truncated": self.source_excerpt_truncated,
        }


@dataclass(frozen=True, slots=True)
class ReflectionTrigger:
    trigger_id: str
    kind: ReflectionTriggerKind
    source_refs: tuple[str, ...]
    source_context_revision: int
    priority: int
    interruptible: bool
    created_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.trigger_id, "trigger_id")
        if not isinstance(self.kind, ReflectionTriggerKind):
            raise ValueError("kindが不正です")
        refs = _identifiers(self.source_refs, "source_refs")
        if not refs:
            raise ValueError("source_refsは空にできません")
        object.__setattr__(self, "source_refs", refs)
        require_revision(self.source_context_revision, "source_context_revision")
        if type(self.priority) is not int or not 0 <= self.priority <= 100:
            raise ValueError("priorityが不正です")
        if type(self.interruptible) is not bool:
            raise ValueError("interruptibleが不正です")
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ReflectionRelatedMemory:
    memory_id: str
    revision: int

    def __post_init__(self) -> None:
        require_identifier(self.memory_id, "memory_id")
        require_revision(self.revision, "revision")


@dataclass(frozen=True, slots=True)
class ReflectionContextSnapshot:
    reflection_id: str
    trigger: ReflectionTrigger
    primary_sources: tuple[ReflectionSourceEvidence, ...]
    related_memory_view: tuple[ReflectionRelatedMemory, ...]
    source_context_revision: int
    memory_store_revision: int | None
    captured_at: datetime
    trace_id: str
    operational_policy_id: str
    operational_policy_revision: int
    character_self_model_view: JsonValue | None = None
    value_disposition_view: JsonValue | None = None
    estimated_tokens: int = 0

    def __post_init__(self) -> None:
        require_identifier(self.reflection_id, "reflection_id")
        if not isinstance(self.trigger, ReflectionTrigger):
            raise ValueError("triggerが不正です")
        sources = _owned(
            self.primary_sources,
            ReflectionSourceEvidence,
            "primary_sources",
        )
        if not sources:
            raise ValueError("primary_sourcesは空にできません")
        if len({source.source_ref for source in sources}) != len(sources):
            raise ValueError("primary_sourcesが重複しています")
        if {source.source_ref for source in sources} != set(self.trigger.source_refs):
            raise ValueError("primary_sourcesとtrigger source_refsが一致しません")
        object.__setattr__(self, "primary_sources", sources)
        memories = _owned(
            self.related_memory_view,
            ReflectionRelatedMemory,
            "related_memory_view",
        )
        if len({memory.memory_id for memory in memories}) != len(memories):
            raise ValueError("related_memory_viewが重複しています")
        object.__setattr__(self, "related_memory_view", memories)
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.memory_store_revision, "memory_store_revision", optional=True)
        require_aware(self.captured_at, "captured_at")
        require_identifier(self.trace_id, "trace_id")
        require_identifier(self.operational_policy_id, "operational_policy_id")
        require_revision(self.operational_policy_revision, "operational_policy_revision")
        for name in ("character_self_model_view", "value_disposition_view"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _bounded_payload(value, name, maximum_bytes=4_096))
        if type(self.estimated_tokens) is not int or self.estimated_tokens < 0:
            raise ValueError("estimated_tokensが不正です")
        object.__setattr__(
            self,
            "estimated_tokens",
            estimate_memory_token_units(self._budget_payload()),
        )

    def _budget_payload(self) -> dict[str, object]:
        return {
            "reflection_id": self.reflection_id,
            "trigger": {
                "trigger_id": self.trigger.trigger_id,
                "kind": self.trigger.kind.value,
                "source_refs": list(self.trigger.source_refs),
                "source_context_revision": self.trigger.source_context_revision,
                "priority": self.trigger.priority,
                "interruptible": self.trigger.interruptible,
                "created_at": self.trigger.created_at.isoformat(),
            },
            "primary_sources": [source.to_dict() for source in self.primary_sources],
            "related_memory_view": [
                {"memory_id": item.memory_id, "revision": item.revision}
                for item in self.related_memory_view
            ],
            "source_context_revision": self.source_context_revision,
            "memory_store_revision": self.memory_store_revision,
            "captured_at": self.captured_at.isoformat(),
            "trace_id": self.trace_id,
            "operational_policy_id": self.operational_policy_id,
            "operational_policy_revision": self.operational_policy_revision,
            "character_self_model_view": None
            if self.character_self_model_view is None
            else thaw_json(self.character_self_model_view),
            "value_disposition_view": None
            if self.value_disposition_view is None
            else thaw_json(self.value_disposition_view),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._budget_payload(), "estimated_tokens": self.estimated_tokens}


@dataclass(frozen=True, slots=True)
class ReflectionRelationHint:
    related_memory_id: str
    related_memory_revision: int
    relation_kind: MemoryRelationKind
    evidence_refs: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        require_identifier(self.related_memory_id, "related_memory_id")
        require_revision(self.related_memory_revision, "related_memory_revision")
        if not isinstance(self.relation_kind, MemoryRelationKind):
            raise ValueError("relation_kindが不正です")
        refs = _identifiers(self.evidence_refs, "evidence_refs")
        if not refs:
            raise ValueError("evidence_refsは空にできません")
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(self, "confidence", _unit(self.confidence, "confidence"))


@dataclass(frozen=True, slots=True)
class MemoryCandidateProposal:
    proposal_id: str
    proposed_kind: MemoryKind
    content: MemoryContent
    source_refs: tuple[str, ...]
    confidence_hint: float
    importance_hint: float
    persistence_hint: ReflectionPersistenceHint
    novelty_hint: float
    temporal: MemoryTemporalState
    suggested_related_memory_ids: tuple[str, ...] = ()
    relation_hints: tuple[ReflectionRelationHint, ...] = ()
    rationale_evidence_refs: tuple[str, ...] = ()
    deterministic_capture: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.proposal_id, "proposal_id")
        if not isinstance(self.proposed_kind, MemoryKind) or not isinstance(
            self.content, MemoryContent
        ):
            raise ValueError("proposed memoryが不正です")
        refs = _identifiers(self.source_refs, "source_refs")
        if not refs:
            raise ValueError("source_refsは空にできません")
        object.__setattr__(self, "source_refs", refs)
        for name in ("confidence_hint", "importance_hint", "novelty_hint"):
            object.__setattr__(self, name, _unit(getattr(self, name), name))
        if not isinstance(self.persistence_hint, ReflectionPersistenceHint):
            raise ValueError("persistence_hintが不正です")
        if not isinstance(self.temporal, MemoryTemporalState):
            raise ValueError("temporalが不正です")
        object.__setattr__(
            self,
            "suggested_related_memory_ids",
            _identifiers(self.suggested_related_memory_ids, "suggested_related_memory_ids"),
        )
        hints = _owned(self.relation_hints, ReflectionRelationHint, "relation_hints")
        if len({hint.related_memory_id for hint in hints}) != len(hints):
            raise ValueError("relation_hintsが重複しています")
        object.__setattr__(self, "relation_hints", hints)
        object.__setattr__(
            self,
            "rationale_evidence_refs",
            _identifiers(self.rationale_evidence_refs, "rationale_evidence_refs"),
        )
        if type(self.deterministic_capture) is not bool:
            raise ValueError("deterministic_captureが不正です")


@dataclass(frozen=True, slots=True)
class ReflectionSupportObservation:
    proposal_id: str
    support_relation: ReflectionSupportRelation
    evidence_refs: tuple[str, ...]
    unsupported_content_refs: tuple[str, ...]
    contradiction_refs: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        require_identifier(self.proposal_id, "proposal_id")
        if not isinstance(self.support_relation, ReflectionSupportRelation):
            raise ValueError("support_relationが不正です")
        object.__setattr__(self, "evidence_refs", _identifiers(self.evidence_refs, "evidence_refs"))
        object.__setattr__(
            self,
            "unsupported_content_refs",
            _identifiers(self.unsupported_content_refs, "unsupported_content_refs"),
        )
        object.__setattr__(
            self,
            "contradiction_refs",
            _identifiers(self.contradiction_refs, "contradiction_refs"),
        )
        object.__setattr__(self, "confidence", _unit(self.confidence, "confidence"))
        if self.support_relation is ReflectionSupportRelation.SUPPORTED:
            if not self.evidence_refs or self.unsupported_content_refs or self.contradiction_refs:
                raise ValueError("SUPPORTED observationのevidenceが不正です")
        elif self.support_relation is ReflectionSupportRelation.UNSUPPORTED:
            if self.contradiction_refs:
                raise ValueError("UNSUPPORTED observationのevidenceが不正です")
        elif self.support_relation is ReflectionSupportRelation.CONTRADICTED:
            if not self.contradiction_refs or self.unsupported_content_refs:
                raise ValueError("CONTRADICTED observationのevidenceが不正です")
        elif self.unsupported_content_refs or self.contradiction_refs:
            raise ValueError("support observationのevidenceが不正です")


@dataclass(frozen=True, slots=True)
class ReflectionAcceptancePolicy:
    policy_id: str
    policy_revision: int
    durable_requires_supported: bool = True

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        if type(self.durable_requires_supported) is not bool:
            raise ValueError("durable_requires_supportedが不正です")


@dataclass(frozen=True, slots=True)
class ReflectionCandidateResult:
    proposal_id: str
    status: ReflectionCandidateStatus
    candidate: ValidatedMemoryCandidate | None
    diagnostic_refs: tuple[str, ...]
    relation_hints: tuple[ReflectionRelationHint, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.proposal_id, "proposal_id")
        if not isinstance(self.status, ReflectionCandidateStatus):
            raise ValueError("statusが不正です")
        if self.candidate is not None and not isinstance(self.candidate, ValidatedMemoryCandidate):
            raise ValueError("candidateが不正です")
        if (self.status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION) != (
            self.candidate is not None
        ):
            raise ValueError("statusとcandidateの対応が不正です")
        object.__setattr__(
            self,
            "diagnostic_refs",
            _identifiers(self.diagnostic_refs, "diagnostic_refs"),
        )
        hints = _owned(self.relation_hints, ReflectionRelationHint, "relation_hints")
        if self.candidate is None and hints:
            raise ValueError("reject済みresultにrelation_hintsを含められません")
        object.__setattr__(self, "relation_hints", hints)


@dataclass(frozen=True, slots=True)
class ReflectionRunTelemetry:
    event_kinds: tuple[ReflectionEventKind, ...]
    trigger_kind: ReflectionTriggerKind
    source_item_count: int
    estimated_tokens: int
    proposal_count: int
    accepted_count: int
    rejected_counts: tuple[tuple[ReflectionCandidateStatus, int], ...]
    proposal_latency_ms: float
    support_latency_ms: float

    def __post_init__(self) -> None:
        events = _owned(self.event_kinds, ReflectionEventKind, "event_kinds", maximum=64)
        if not events:
            raise ValueError("event_kindsは空にできません")
        object.__setattr__(self, "event_kinds", events)
        if not isinstance(self.trigger_kind, ReflectionTriggerKind):
            raise ValueError("trigger_kindが不正です")
        for name in ("source_item_count", "estimated_tokens", "proposal_count", "accepted_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name}が不正です")
        if self.accepted_count > self.proposal_count:
            raise ValueError("accepted_countがproposal_countを超えています")
        counts = _owned(self.rejected_counts, tuple, "rejected_counts", maximum=16)
        if any(
            len(item) != 2
            or not isinstance(item[0], ReflectionCandidateStatus)
            or type(item[1]) is not int
            or item[1] < 1
            for item in counts
        ):
            raise ValueError("rejected_countsが不正です")
        if len({item[0] for item in counts}) != len(counts):
            raise ValueError("rejected_countsが重複しています")
        rejected_counts = cast(
            tuple[tuple[ReflectionCandidateStatus, int], ...],
            counts,
        )
        object.__setattr__(self, "rejected_counts", rejected_counts)
        for name in ("proposal_latency_ms", "support_latency_ms"):
            value = getattr(self, name)
            if type(value) not in {int, float} or not isfinite(float(value)) or value < 0:
                raise ValueError(f"{name}が不正です")
            object.__setattr__(self, name, float(value))


@dataclass(frozen=True, slots=True)
class ReflectionRunResult:
    reflection_id: str
    results: tuple[ReflectionCandidateResult, ...]
    coalesced_source_refs: tuple[str, ...] = ()
    telemetry: ReflectionRunTelemetry | None = None

    def __post_init__(self) -> None:
        require_identifier(self.reflection_id, "reflection_id")
        object.__setattr__(
            self,
            "results",
            _owned(self.results, ReflectionCandidateResult, "results"),
        )
        object.__setattr__(
            self,
            "coalesced_source_refs",
            _identifiers(self.coalesced_source_refs, "coalesced_source_refs"),
        )
        if self.telemetry is not None and not isinstance(self.telemetry, ReflectionRunTelemetry):
            raise ValueError("telemetryが不正です")


def source_kind_to_memory_kind(source_kind: ReflectionSourceKind) -> MemorySourceKind:
    if source_kind is ReflectionSourceKind.PRESENTATION_FACT:
        return MemorySourceKind.PRESENTATION_OBSERVATION
    if source_kind is ReflectionSourceKind.EXECUTION_FACT:
        return MemorySourceKind.ACTUAL_EXECUTION_FACT
    if source_kind is ReflectionSourceKind.MEMORY_EVIDENCE:
        return MemorySourceKind.REFLECTION_CANDIDATE
    return MemorySourceKind.TYPED_EVENT


def candidate_from_accepted_proposal(
    proposal: MemoryCandidateProposal,
    context: ReflectionContextSnapshot,
    support: ReflectionSupportObservation,
) -> ValidatedMemoryCandidate:
    source_map = {source.source_ref: source for source in context.primary_sources}
    sources = tuple(source_map[source_ref] for source_ref in proposal.source_refs)
    primary = next(
        (
            source
            for source in sources
            if proposal.content.predicate == "actual_speech"
            and source.source_kind is ReflectionSourceKind.PRESENTATION_FACT
        ),
        next(
            (
                source
                for source in sources
                if proposal.content.predicate == "executed_activity"
                and source.source_kind is ReflectionSourceKind.EXECUTION_FACT
            ),
            sources[0],
        ),
    )
    event_refs = tuple(
        source.source_ref
        for source in sources
        if source.source_kind is not ReflectionSourceKind.EXECUTION_FACT
    )
    fact_refs = tuple(
        source.source_ref
        for source in sources
        if source.source_kind is ReflectionSourceKind.EXECUTION_FACT
    )
    provenance = MemoryProvenance(
        source_kind_to_memory_kind(primary.source_kind),
        event_refs,
        fact_refs,
        proposal.proposal_id,
        max(source.occurred_at for source in sources),
        context.captured_at,
    )
    confidence = MemoryConfidence(
        min(proposal.confidence_hint, support.confidence),
        "reflection_support",
    )
    return ValidatedMemoryCandidate(
        proposal.proposal_id,
        proposal.proposed_kind,
        proposal.content,
        provenance,
        confidence,
        proposal.temporal,
        context.captured_at,
        proposal.importance_hint,
        proposal.suggested_related_memory_ids,
        context.source_context_revision,
        primary.source_kind is ReflectionSourceKind.PRESENTATION_FACT,
        primary.source_kind is ReflectionSourceKind.EXECUTION_FACT,
    )
