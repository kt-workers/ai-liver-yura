"""Memory Ownerの明示された意味だけを公開し、利用不能を型として保持する。"""

from dataclasses import dataclass
from enum import Enum

from app.domain.contracts.common import JsonValue, require_identifier, require_revision
from app.domain.memory.contracts import (
    MemoryAssertionCertainty,
    MemoryAssertionPolarity,
    MemoryAssertionSemantics,
    MemoryAssertionTemporalMeaning,
    MemoryConfidence,
    MemoryContent,
    MemoryEvidenceItem,
    MemoryFreshnessState,
    MemoryKind,
    MemoryLifecycle,
    MemoryProvenance,
    MemoryRecord,
    MemoryTemporalState,
)
from app.domain.memory.ranking import RankedMemoryEvidenceView


class MemorySemanticAssertionUnavailableReason(str, Enum):
    SEMANTICS_UNRESOLVED = "semantics_unresolved"
    SUBJECT_UNRESOLVED = "subject_unresolved"
    STALE = "stale"
    CONFLICTED = "conflicted"
    INACTIVE_LIFECYCLE = "inactive_lifecycle"
    PROVENANCE_UNAVAILABLE = "provenance_unavailable"
    DEGRADED_VIEW = "degraded_view"
    TEMPORAL_INCONSISTENCY = "temporal_inconsistency"
    REVISION_STALE = "revision_stale"
    SOURCE_NOT_FOUND = "source_not_found"
    REPOSITORY_UNAVAILABLE = "repository_unavailable"
    FINALIZATION_UNSUPPORTED = "finalization_unsupported"


R = MemorySemanticAssertionUnavailableReason


def _unavailable(
    content: MemoryContent,
    semantics: MemoryAssertionSemantics | None,
    temporal: MemoryTemporalState,
    lifecycle: MemoryLifecycle,
    provenance: tuple[MemoryProvenance, ...],
    conflicts: tuple[str, ...],
) -> R | None:
    if semantics is None:
        return R.SEMANTICS_UNRESOLVED
    if content.subject_ref is None:
        return R.SUBJECT_UNRESOLVED
    if lifecycle is not MemoryLifecycle.ACTIVE:
        return R.INACTIVE_LIFECYCLE
    if temporal.freshness is MemoryFreshnessState.STALE:
        return R.STALE
    if conflicts:
        return R.CONFLICTED
    if not provenance or not all(p.has_evidence for p in provenance):
        return R.PROVENANCE_UNAVAILABLE
    if (
        temporal.freshness is MemoryFreshnessState.HISTORICAL
        and semantics.temporal_meaning is MemoryAssertionTemporalMeaning.CURRENT
    ):
        return R.TEMPORAL_INCONSISTENCY
    return None


@dataclass(frozen=True, slots=True)
class MemorySemanticAssertion:
    memory_id: str
    memory_revision: int
    memory_kind: MemoryKind
    content: MemoryContent
    assertion_semantics: MemoryAssertionSemantics
    provenance: tuple[MemoryProvenance, ...]
    confidence: MemoryConfidence
    temporal: MemoryTemporalState
    lifecycle: MemoryLifecycle
    contradiction_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.memory_id, "memory_id")
        require_revision(self.memory_revision, "memory_revision")
        if (
            not isinstance(self.memory_kind, MemoryKind)
            or not isinstance(self.content, MemoryContent)
            or not isinstance(self.assertion_semantics, MemoryAssertionSemantics)
            or not isinstance(self.confidence, MemoryConfidence)
            or not isinstance(self.temporal, MemoryTemporalState)
            or not isinstance(self.lifecycle, MemoryLifecycle)
        ):
            raise ValueError("Memory assertionの型が不正です")
        provenance = tuple(self.provenance)
        if any(not isinstance(p, MemoryProvenance) for p in provenance):
            raise ValueError("Memory assertionのprovenanceが不正です")
        conflicts = tuple(self.contradiction_refs)
        if (
            _unavailable(
                self.content,
                self.assertion_semantics,
                self.temporal,
                self.lifecycle,
                provenance,
                conflicts,
            )
            is not None
        ):
            raise ValueError("利用不能のMemoryをassertionとして公開できません")
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "contradiction_refs", conflicts)

    @property
    def subject_ref(self) -> str:
        assert self.content.subject_ref is not None
        return self.content.subject_ref

    @property
    def predicate(self) -> str:
        return self.content.predicate

    @property
    def value(self) -> JsonValue:
        return self.content.value

    @property
    def temporal_scope_ref(self) -> str | None:
        return self.content.temporal_scope_ref

    @property
    def qualifiers(self) -> tuple[str, ...]:
        return self.content.qualifiers

    @property
    def polarity(self) -> MemoryAssertionPolarity:
        return self.assertion_semantics.polarity

    @property
    def certainty(self) -> MemoryAssertionCertainty:
        return self.assertion_semantics.certainty

    @property
    def temporal_meaning(self) -> MemoryAssertionTemporalMeaning:
        return self.assertion_semantics.temporal_meaning


@dataclass(frozen=True, slots=True)
class MemorySemanticAssertionEntry:
    memory_id: str
    memory_revision: int | None
    assertion: MemorySemanticAssertion | None = None
    unavailable_reason: R | None = None

    def __post_init__(self) -> None:
        require_identifier(self.memory_id, "memory_id")
        require_revision(self.memory_revision, "memory_revision", optional=True)
        if (self.assertion is None) == (self.unavailable_reason is None):
            raise ValueError("assertionまたは利用不能理由の一方だけが必要です")
        if self.unavailable_reason is not None and not isinstance(self.unavailable_reason, R):
            raise ValueError("利用不能理由の型が不正です")
        if self.assertion is not None and (
            not isinstance(self.assertion, MemorySemanticAssertion)
            or self.assertion.memory_id != self.memory_id
            or self.assertion.memory_revision != self.memory_revision
        ):
            raise ValueError("assertionのidentity/revisionが一致しません")


@dataclass(frozen=True, slots=True)
class MemorySemanticAssertionView:
    source: RankedMemoryEvidenceView
    entries: tuple[MemorySemanticAssertionEntry, ...]
    unavailable_reason: R | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, RankedMemoryEvidenceView):
            raise ValueError("元のranked Memory evidenceが必要です")
        entries = tuple(self.entries)
        if any(not isinstance(e, MemorySemanticAssertionEntry) for e in entries):
            raise ValueError("Memory assertion entryの型が不正です")
        if tuple((e.memory_id, e.memory_revision) for e in entries) != tuple(
            (i.memory_id, i.memory_revision) for i in self.source.items
        ):
            raise ValueError("元のMemory順位とrevisionを保持する必要があります")
        if self.source.degraded:
            if self.unavailable_reason is not R.DEGRADED_VIEW or any(
                e.unavailable_reason is not R.DEGRADED_VIEW for e in entries
            ):
                raise ValueError("degraded view全体を利用不能にする必要があります")
        elif self.unavailable_reason is not None:
            raise ValueError("正常viewへ全体利用不能理由を付けられません")
        object.__setattr__(self, "entries", entries)

    @property
    def truncated(self) -> bool:
        return self.source.truncated

    @property
    def degraded(self) -> bool:
        return self.source.degraded


def semantic_assertion_entry(
    source: MemoryRecord | MemoryEvidenceItem, conflicts: tuple[str, ...]
) -> MemorySemanticAssertionEntry:
    revision = source.revision if isinstance(source, MemoryRecord) else source.memory_revision
    reason = _unavailable(
        source.content,
        source.assertion_semantics,
        source.temporal,
        source.lifecycle,
        source.provenance,
        conflicts,
    )
    if reason is not None:
        return MemorySemanticAssertionEntry(source.memory_id, revision, unavailable_reason=reason)
    assert source.assertion_semantics is not None
    return MemorySemanticAssertionEntry(
        source.memory_id,
        revision,
        MemorySemanticAssertion(
            source.memory_id,
            revision,
            source.kind,
            source.content,
            source.assertion_semantics,
            source.provenance,
            source.confidence,
            source.temporal,
            source.lifecycle,
            conflicts,
        ),
    )


def project_memory_semantic_assertions(
    source: RankedMemoryEvidenceView,
) -> MemorySemanticAssertionView:
    if not isinstance(source, RankedMemoryEvidenceView):
        raise ValueError("元のranked Memory evidenceが必要です")
    if source.degraded:
        return MemorySemanticAssertionView(
            source,
            tuple(
                MemorySemanticAssertionEntry(
                    i.memory_id, i.memory_revision, unavailable_reason=R.DEGRADED_VIEW
                )
                for i in source.items
            ),
            R.DEGRADED_VIEW,
        )
    return MemorySemanticAssertionView(
        source, tuple(semantic_assertion_entry(i, i.contradiction_refs) for i in source.items)
    )
