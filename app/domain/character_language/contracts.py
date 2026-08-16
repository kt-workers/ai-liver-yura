from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import datetime
from enum import Enum
from typing import TypeVar, cast

from app.domain.character import RuntimeAvailability
from app.domain.character.contracts import CharacterLanguageProfile, RuntimeCharacterFacet
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import require_aware, require_identifier, utc_instant
from app.domain.speech_semantics import (
    SpeechPropositionDisposition,
    SpeechSemanticCandidate,
    SpeechSemanticPlan,
)


class CharacterLanguageConstraintKind(str, Enum):
    RELATIONSHIP = "relationship"
    DISCOURSE = "discourse"


class LinguisticBoundary(str, Enum):
    CONTINUE = "continue"
    PHRASE = "phrase"
    SENTENCE = "sentence"


class LinguisticEmphasis(str, Enum):
    NEUTRAL = "neutral"
    EMPHASIZED = "emphasized"
    DEEMPHASIZED = "deemphasized"


class LinguisticHesitation(str, Enum):
    NONE = "none"
    HESITANT = "hesitant"


class CharacterLanguageFailureCode(str, Enum):
    SCHEMA_INVALID = "schema_invalid"
    STALE = "stale"
    SUPERSEDED = "superseded"
    PROFILE_STALE = "profile_stale"
    CONSTRAINT_STALE = "constraint_stale"
    UNAVAILABLE = "unavailable"


class CharacterLanguageError(ValueError):
    def __init__(self, code: CharacterLanguageFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


T = TypeVar("T")
_UTTERANCE_PROOF = object()


def _owned(values: object, expected: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} は配列でなければなりません")
    result = tuple(values)
    if any(not isinstance(item, expected) for item in result):
        raise ValueError(f"{name} に不正な値があります")
    return cast(tuple[T, ...], result)


def _identifiers(values: object, name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    result = _owned(values, str, name)
    if any(not value.strip() for value in result):
        raise ValueError(f"{name} は空でない文字列だけを含めなければなりません")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} は重複できません")
    if non_empty and not result:
        raise ValueError(f"{name} は空にできません")
    return result


def _non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} は0以上の整数でなければなりません")
    return value


@dataclass(frozen=True, slots=True)
class CharacterLanguageConstraintView:
    constraint_id: str
    kind: CharacterLanguageConstraintKind
    source_owner: str
    source_ref: str
    source_revision: int
    language_guidance: str

    def __post_init__(self) -> None:
        for name in ("constraint_id", "source_owner", "source_ref", "language_guidance"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.kind, CharacterLanguageConstraintKind):
            raise ValueError("kind は CharacterLanguageConstraintKind でなければなりません")
        _non_negative_int(self.source_revision, "source_revision")

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "kind": self.kind.value,
            "source_owner": self.source_owner,
            "source_ref": self.source_ref,
            "source_revision": self.source_revision,
            "language_guidance": self.language_guidance,
        }


@dataclass(frozen=True, slots=True)
class CharacterUtteranceSegment:
    segment_id: str
    text: str
    realization_refs: tuple[str, ...]
    boundary_after: LinguisticBoundary
    emphasis: LinguisticEmphasis
    hesitation: LinguisticHesitation

    def __post_init__(self) -> None:
        require_identifier(self.segment_id, "segment_id")
        require_identifier(self.text, "text")
        object.__setattr__(
            self, "realization_refs", _identifiers(self.realization_refs, "realization_refs")
        )
        if not isinstance(self.boundary_after, LinguisticBoundary):
            raise ValueError("boundary_after は LinguisticBoundary でなければなりません")
        if not isinstance(self.emphasis, LinguisticEmphasis):
            raise ValueError("emphasis は LinguisticEmphasis でなければなりません")
        if not isinstance(self.hesitation, LinguisticHesitation):
            raise ValueError("hesitation は LinguisticHesitation でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "text": self.text,
            "realization_refs": list(self.realization_refs),
            "boundary_after": self.boundary_after.value,
            "emphasis": self.emphasis.value,
            "hesitation": self.hesitation.value,
        }


@dataclass(frozen=True, slots=True)
class CharacterLanguageContextSnapshot:
    request_id: str
    semantic_plan: SpeechSemanticPlan
    character_profile: CharacterLanguageProfile
    constraints: tuple[CharacterLanguageConstraintView, ...]
    captured_at: datetime
    trace_id: str

    def __post_init__(self) -> None:
        require_identifier(self.request_id, "request_id")
        require_identifier(self.trace_id, "trace_id")
        if not isinstance(self.semantic_plan, SpeechSemanticPlan):
            raise ValueError("semantic_plan は SpeechSemanticPlan でなければなりません")
        if not isinstance(self.character_profile, CharacterLanguageProfile):
            raise ValueError("character_profile は CharacterLanguageProfile でなければなりません")
        constraints = _owned(self.constraints, CharacterLanguageConstraintView, "constraints")
        if len({item.constraint_id for item in constraints}) != len(constraints):
            raise ValueError("constraint_id は一意でなければなりません")
        object.__setattr__(self, "constraints", constraints)
        require_aware(self.captured_at, "captured_at")
        if utc_instant(self.captured_at) < utc_instant(self.semantic_plan.committed_at):
            raise ValueError("snapshot はcommit済みPlanより前にできません")
        self._validate_constraints()

    @property
    def candidate(self) -> SpeechSemanticCandidate:
        return self.semantic_plan.candidate

    @property
    def revisions(self) -> RevisionVector:
        return self.candidate.revisions

    @property
    def source_event_ids(self) -> tuple[str, ...]:
        return self.candidate.source_event_ids

    @property
    def confirmed_facets(self) -> tuple[RuntimeCharacterFacet, ...]:
        return tuple(
            item
            for item in self.character_profile.facets
            if item.availability is RuntimeAvailability.CONFIRMED
        )

    def _validate_constraints(self) -> None:
        candidate = self.candidate
        expected = {
            *(
                (ref, CharacterLanguageConstraintKind.RELATIONSHIP)
                for ref in candidate.relationship_constraint_refs
            ),
            *(
                (ref, CharacterLanguageConstraintKind.DISCOURSE)
                for ref in candidate.discourse_constraint_refs
            ),
        }
        actual = {(item.constraint_id, item.kind) for item in self.constraints}
        if actual != expected:
            raise ValueError(
                "Plan constraint refs はtyped constraint viewと完全一致しなければなりません"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "semantic_plan": self.semantic_plan.to_dict(),
            "character_profile": {
                "character_id": self.character_profile.character_id,
                "schema_version": self.character_profile.schema_version,
                "definition_revision": self.character_profile.definition_revision,
                "facets": [
                    {
                        "facet_id": item.facet_id,
                        "value": item.value,
                        "basis_refs": list(item.basis_refs),
                    }
                    for item in self.confirmed_facets
                ],
            },
            "constraints": [item.to_dict() for item in self.constraints],
            "source_event_ids": list(self.source_event_ids),
            "revisions": self.revisions.to_dict(),
            "captured_at": self.captured_at.isoformat(),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class CharacterUtteranceCandidate:
    candidate_id: str
    request_id: str
    semantic_plan_id: str
    source_decision_id: str
    source_intent_id: str
    source_event_ids: tuple[str, ...]
    revisions: RevisionVector
    character_id: str
    character_schema_version: int
    character_definition_revision: int
    segments: tuple[CharacterUtteranceSegment, ...]
    question_budget_used: int
    new_direction_budget_used: int
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "request_id",
            "semantic_plan_id",
            "source_decision_id",
            "source_intent_id",
            "character_id",
        ):
            require_identifier(getattr(self, name), name)
        object.__setattr__(
            self,
            "source_event_ids",
            _identifiers(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions は RevisionVector でなければなりません")
        _non_negative_int(self.character_schema_version, "character_schema_version")
        _non_negative_int(self.character_definition_revision, "character_definition_revision")
        segments = _owned(self.segments, CharacterUtteranceSegment, "segments")
        if not segments:
            raise ValueError("segments は空にできません")
        if len({item.segment_id for item in segments}) != len(segments):
            raise ValueError("segment_id は一意でなければなりません")
        object.__setattr__(self, "segments", segments)
        _non_negative_int(self.question_budget_used, "question_budget_used")
        _non_negative_int(self.new_direction_budget_used, "new_direction_budget_used")
        require_aware(self.created_at, "created_at")

    @property
    def realization_refs(self) -> tuple[str, ...]:
        return tuple(ref for segment in self.segments for ref in segment.realization_refs)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "request_id": self.request_id,
            "semantic_plan_id": self.semantic_plan_id,
            "source_decision_id": self.source_decision_id,
            "source_intent_id": self.source_intent_id,
            "source_event_ids": list(self.source_event_ids),
            "revisions": self.revisions.to_dict(),
            "character_id": self.character_id,
            "character_schema_version": self.character_schema_version,
            "character_definition_revision": self.character_definition_revision,
            "segments": [item.to_dict() for item in self.segments],
            "question_budget_used": self.question_budget_used,
            "new_direction_budget_used": self.new_direction_budget_used,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class CharacterUtterance:
    utterance_id: str
    candidate: CharacterUtteranceCandidate
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        require_identifier(self.utterance_id, "utterance_id")
        if not isinstance(self.candidate, CharacterUtteranceCandidate):
            raise ValueError("candidate は CharacterUtteranceCandidate でなければなりません")
        require_aware(self.committed_at, "committed_at")
        if utc_instant(self.committed_at) < utc_instant(self.candidate.created_at):
            raise ValueError("committed_at はcandidate作成時刻より前にできません")
        if _proof is not _UTTERANCE_PROOF:
            raise ValueError("CharacterUtterance の構築には CharacterLanguageAuthority が必要です")

    def to_dict(self) -> dict[str, object]:
        return {
            "utterance_id": self.utterance_id,
            "candidate": self.candidate.to_dict(),
            "committed_at": self.committed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class CharacterLanguageCommitState:
    revisions: RevisionVector
    semantic_plan: SpeechSemanticPlan | None
    semantic_plan_eligible: bool
    character_profile: CharacterLanguageProfile | None
    constraints: tuple[CharacterLanguageConstraintView, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions は RevisionVector でなければなりません")
        if self.semantic_plan is not None and not isinstance(
            self.semantic_plan, SpeechSemanticPlan
        ):
            raise ValueError("semantic_plan は SpeechSemanticPlan 又は None でなければなりません")
        if type(self.semantic_plan_eligible) is not bool:
            raise ValueError("semantic_plan_eligible はboolでなければなりません")
        if self.character_profile is not None and not isinstance(
            self.character_profile, CharacterLanguageProfile
        ):
            raise ValueError(
                "character_profile は CharacterLanguageProfile 又は None でなければなりません"
            )
        constraints = _owned(self.constraints, CharacterLanguageConstraintView, "constraints")
        if len({item.constraint_id for item in constraints}) != len(constraints):
            raise ValueError("constraint_id は一意でなければなりません")
        object.__setattr__(self, "constraints", constraints)


def validate_candidate_structure(
    candidate: CharacterUtteranceCandidate,
    snapshot: CharacterLanguageContextSnapshot,
) -> None:
    if candidate.request_id != snapshot.request_id:
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "candidate requestがsnapshotと一致しません"
        )
    plan_candidate = snapshot.candidate
    if (
        candidate.semantic_plan_id != snapshot.semantic_plan.plan_id
        or candidate.source_decision_id != plan_candidate.decision_id
        or candidate.source_intent_id != plan_candidate.intent_id
        or candidate.source_event_ids != plan_candidate.source_event_ids
        or candidate.revisions != plan_candidate.revisions
    ):
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "candidate provenanceがPlanと一致しません"
        )
    profile = snapshot.character_profile
    if (
        candidate.character_id != profile.character_id
        or candidate.character_schema_version != profile.schema_version
        or candidate.character_definition_revision != profile.definition_revision
    ):
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID,
            "candidate Character provenanceが一致しません",
        )
    if utc_instant(candidate.created_at) < utc_instant(snapshot.captured_at):
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "candidateがsnapshotより前です"
        )
    propositions = {item.proposition_id: item for item in plan_candidate.propositions}
    if any(ref not in propositions for ref in candidate.realization_refs):
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "未知のrealization refがあります"
        )
    if any(
        propositions[ref].disposition is SpeechPropositionDisposition.FORBIDDEN
        for ref in candidate.realization_refs
    ):
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "FORBIDDEN propositionは実現できません"
        )
    required = {
        item.proposition_id
        for item in plan_candidate.propositions
        if item.disposition is SpeechPropositionDisposition.REQUIRED
    }
    if not required.issubset(candidate.realization_refs):
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "REQUIRED propositionが不足しています"
        )
    if candidate.question_budget_used > plan_candidate.question_budget:
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "question budgetを超えています"
        )
    if candidate.new_direction_budget_used > plan_candidate.new_direction_budget:
        raise CharacterLanguageError(
            CharacterLanguageFailureCode.SCHEMA_INVALID, "new direction budgetを超えています"
        )
