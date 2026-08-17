from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import datetime
from enum import Enum
from typing import TypeVar, cast

from app.domain.character_language import CharacterUtterance
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import require_aware, require_identifier, timestamp_to_json, utc_instant
from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_semantics import SpeechSemanticPlan


class BlindSemanticUnitKind(str, Enum):
    MATERIAL_CLAIM = "material_claim"
    DIRECTED_QUESTION = "directed_question"
    NEW_DIRECTION = "new_direction"
    NON_PROPOSITIONAL_STYLE = "non_propositional_style"
    AMBIGUOUS = "ambiguous"


class PropositionRelation(str, Enum):
    ENTAILED = "entailed"
    MISSING = "missing"
    CONTRADICTED = "contradicted"
    AMBIGUOUS = "ambiguous"


class PolarityRelation(str, Enum):
    PRESERVED = "preserved"
    REVERSED = "reversed"
    UNKNOWN_COMMITTED = "unknown_committed"
    KNOWN_LOST_TO_UNKNOWN = "known_lost_to_unknown"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"


class CertaintyRelation(str, Enum):
    PRESERVED = "preserved"
    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"
    LOST_TO_UNKNOWN = "lost_to_unknown"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"


class DegreeRelation(str, Enum):
    PRESERVED = "preserved"
    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"
    OMITTED = "omitted"
    ADDED = "added"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"


class ExecutionRelation(str, Enum):
    PRESERVED = "preserved"
    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"
    CONTRADICTED = "contradicted"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"


class BlindUnitAccountingRelation(str, Enum):
    SUPPORTED_BY_PLAN = "supported_by_plan"
    UNSUPPORTED_EXTRA = "unsupported_extra"
    PERMITTED_NON_PROPOSITIONAL_STYLE = "permitted_non_propositional_style"
    QUESTION_OR_DIRECTION = "question_or_direction"
    AMBIGUOUS = "ambiguous"


class SelfDisclosureRelation(str, Enum):
    WITHIN_POLICY = "within_policy"
    EXCEEDED = "exceeded"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"


class SemanticAcceptanceState(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SemanticRejectionCategory(str, Enum):
    REQUIRED_PROPOSITION_MISSING = "required_proposition_missing"
    FORBIDDEN_PROPOSITION_REALIZED = "forbidden_proposition_realized"
    PROPOSITION_CONTRADICTED = "proposition_contradicted"
    POLARITY_CHANGED = "polarity_changed"
    CERTAINTY_CHANGED = "certainty_changed"
    DEGREE_CHANGED = "degree_changed"
    EXECUTION_TRUTH_CHANGED = "execution_truth_changed"
    UNSUPPORTED_EXTRA_CLAIM = "unsupported_extra_claim"
    UNACCOUNTED_MATERIAL_CLAIM = "unaccounted_material_claim"
    QUESTION_BUDGET_EXCEEDED = "question_budget_exceeded"
    NEW_DIRECTION_BUDGET_EXCEEDED = "new_direction_budget_exceeded"
    SELF_DISCLOSURE_EXCEEDED = "self_disclosure_exceeded"
    AMBIGUOUS_SEMANTIC_OBSERVATION = "ambiguous_semantic_observation"
    OBSERVER_DISAGREEMENT = "observer_disagreement"


class SemanticVerificationFailureCode(str, Enum):
    SCHEMA_INVALID = "schema_invalid"
    STALE = "stale"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    PROVIDER_FAILED = "provider_failed"


class SemanticVerificationError(ValueError):
    def __init__(self, code: SemanticVerificationFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


T = TypeVar("T")
_BLIND_PROOF = object()
_RELATION_PROOF = object()
_OBSERVATION_PROOF = object()
_ACCEPTANCE_PROOF = object()


def _owned(values: object, expected: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{name} はarrayでなければなりません")
    result = tuple(values)
    if any(not isinstance(item, expected) for item in result):
        raise ValueError(f"{name} に不正な値があります")
    return cast(tuple[T, ...], result)


def _ids(values: object, name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    result = _owned(values, str, name)
    if any(not item.strip() for item in result):
        raise ValueError(f"{name} は空文字を含められません")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} は重複できません")
    if non_empty and not result:
        raise ValueError(f"{name} は空にできません")
    return result


def _non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} は0以上の整数でなければなりません")
    return value


@dataclass(frozen=True, slots=True)
class UtteranceEvidenceRef:
    segment_id: str
    quote: str
    occurrence_index: int

    def __post_init__(self) -> None:
        require_identifier(self.segment_id, "segment_id")
        require_identifier(self.quote, "quote")
        _non_negative_int(self.occurrence_index, "occurrence_index")
        if len(self.quote) > 1000:
            raise ValueError("quote が長すぎます")

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "quote": self.quote,
            "occurrence_index": self.occurrence_index,
        }


@dataclass(frozen=True, slots=True)
class BlindSemanticUnit:
    unit_id: str
    kind: BlindSemanticUnitKind
    evidence_refs: tuple[UtteranceEvidenceRef, ...]

    def __post_init__(self) -> None:
        require_identifier(self.unit_id, "unit_id")
        if not isinstance(self.kind, BlindSemanticUnitKind):
            raise ValueError("kind は BlindSemanticUnitKind でなければなりません")
        refs = _owned(self.evidence_refs, UtteranceEvidenceRef, "evidence_refs")
        if not refs:
            raise ValueError("blind semantic unitにはevidenceが必要です")
        object.__setattr__(self, "evidence_refs", refs)

    def to_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
        }


@dataclass(frozen=True, slots=True)
class BlindUtteranceObservationCandidate:
    candidate_id: str
    request_id: str
    utterance_id: str
    units: tuple[BlindSemanticUnit, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("candidate_id", "request_id", "utterance_id"):
            require_identifier(getattr(self, name), name)
        units = _owned(self.units, BlindSemanticUnit, "units")
        if len({item.unit_id for item in units}) != len(units):
            raise ValueError("unit_id は一意でなければなりません")
        if len(units) > 64:
            raise ValueError("blind unit数が上限を超えています")
        object.__setattr__(self, "units", units)
        require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class BlindUtteranceObservation:
    observation_id: str
    candidate: BlindUtteranceObservationCandidate
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        require_identifier(self.observation_id, "observation_id")
        if not isinstance(self.candidate, BlindUtteranceObservationCandidate):
            raise ValueError("candidate が不正です")
        require_aware(self.committed_at, "committed_at")
        if utc_instant(self.committed_at) < utc_instant(self.candidate.observed_at):
            raise ValueError("committed_at が observed_at より前です")
        if _proof is not _BLIND_PROOF:
            raise ValueError("BlindUtteranceObservationはAuthority経由でのみ構築できます")

    @property
    def units(self) -> tuple[BlindSemanticUnit, ...]:
        return self.candidate.units

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "utterance_id": self.candidate.utterance_id,
            "units": [item.to_dict() for item in self.units],
            "committed_at": timestamp_to_json(self.committed_at),
        }


@dataclass(frozen=True, slots=True)
class PropositionSemanticObservation:
    proposition_id: str
    relation: PropositionRelation
    polarity_relation: PolarityRelation
    certainty_relation: CertaintyRelation
    degree_relation: DegreeRelation
    execution_relation: ExecutionRelation
    evidence_refs: tuple[UtteranceEvidenceRef, ...]
    supporting_blind_unit_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.proposition_id, "proposition_id")
        for name, expected in (
            ("relation", PropositionRelation),
            ("polarity_relation", PolarityRelation),
            ("certainty_relation", CertaintyRelation),
            ("degree_relation", DegreeRelation),
            ("execution_relation", ExecutionRelation),
        ):
            if not isinstance(getattr(self, name), expected):
                raise ValueError(f"{name} が不正です")
        refs = _owned(self.evidence_refs, UtteranceEvidenceRef, "evidence_refs")
        object.__setattr__(self, "evidence_refs", refs)
        object.__setattr__(
            self,
            "supporting_blind_unit_ids",
            _ids(self.supporting_blind_unit_ids, "supporting_blind_unit_ids"),
        )
        if self.relation is PropositionRelation.ENTAILED and not refs:
            raise ValueError("ENTAILED propositionにはevidenceが必要です")

    def to_dict(self) -> dict[str, object]:
        return {
            "proposition_id": self.proposition_id,
            "relation": self.relation.value,
            "polarity_relation": self.polarity_relation.value,
            "certainty_relation": self.certainty_relation.value,
            "degree_relation": self.degree_relation.value,
            "execution_relation": self.execution_relation.value,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "supporting_blind_unit_ids": list(self.supporting_blind_unit_ids),
        }


@dataclass(frozen=True, slots=True)
class BlindUnitAccounting:
    blind_unit_id: str
    relation: BlindUnitAccountingRelation
    proposition_ids: tuple[str, ...]
    evidence_refs: tuple[UtteranceEvidenceRef, ...]

    def __post_init__(self) -> None:
        require_identifier(self.blind_unit_id, "blind_unit_id")
        if not isinstance(self.relation, BlindUnitAccountingRelation):
            raise ValueError("relation が不正です")
        object.__setattr__(self, "proposition_ids", _ids(self.proposition_ids, "proposition_ids"))
        object.__setattr__(
            self,
            "evidence_refs",
            _owned(self.evidence_refs, UtteranceEvidenceRef, "evidence_refs"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "blind_unit_id": self.blind_unit_id,
            "relation": self.relation.value,
            "proposition_ids": list(self.proposition_ids),
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
        }


@dataclass(frozen=True, slots=True)
class SpeechActBudgetObservation:
    directed_question_count: int
    new_direction_count: int

    def __post_init__(self) -> None:
        _non_negative_int(self.directed_question_count, "directed_question_count")
        _non_negative_int(self.new_direction_count, "new_direction_count")

    def to_dict(self) -> dict[str, int]:
        return {
            "directed_question_count": self.directed_question_count,
            "new_direction_count": self.new_direction_count,
        }


@dataclass(frozen=True, slots=True)
class PlanRelationObservationCandidate:
    candidate_id: str
    request_id: str
    semantic_plan_id: str
    utterance_id: str
    blind_observation_id: str
    proposition_observations: tuple[PropositionSemanticObservation, ...]
    blind_unit_accounting: tuple[BlindUnitAccounting, ...]
    budget_observation: SpeechActBudgetObservation
    self_disclosure_relation: SelfDisclosureRelation
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "request_id",
            "semantic_plan_id",
            "utterance_id",
            "blind_observation_id",
        ):
            require_identifier(getattr(self, name), name)
        observations = _owned(
            self.proposition_observations,
            PropositionSemanticObservation,
            "proposition_observations",
        )
        if len({item.proposition_id for item in observations}) != len(observations):
            raise ValueError("proposition observationは重複できません")
        accounting = _owned(
            self.blind_unit_accounting,
            BlindUnitAccounting,
            "blind_unit_accounting",
        )
        if len({item.blind_unit_id for item in accounting}) != len(accounting):
            raise ValueError("blind unit accountingは重複できません")
        object.__setattr__(self, "proposition_observations", observations)
        object.__setattr__(self, "blind_unit_accounting", accounting)
        if not isinstance(self.budget_observation, SpeechActBudgetObservation):
            raise ValueError("budget_observation が不正です")
        if not isinstance(self.self_disclosure_relation, SelfDisclosureRelation):
            raise ValueError("self_disclosure_relation が不正です")
        require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class PlanRelationObservation:
    observation_id: str
    candidate: PlanRelationObservationCandidate
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        require_identifier(self.observation_id, "observation_id")
        if not isinstance(self.candidate, PlanRelationObservationCandidate):
            raise ValueError("candidate が不正です")
        require_aware(self.committed_at, "committed_at")
        if utc_instant(self.committed_at) < utc_instant(self.candidate.observed_at):
            raise ValueError("committed_at が observed_at より前です")
        if _proof is not _RELATION_PROOF:
            raise ValueError("PlanRelationObservationはAuthority経由でのみ構築できます")


@dataclass(frozen=True, slots=True)
class SemanticVerificationContextSnapshot:
    verification_id: str
    blind_request_id: str
    relation_request_id: str
    semantic_plan: SpeechSemanticPlan
    utterance: CharacterUtterance
    llm_priority: LLMPriority
    interruptibility: LLMInterruptibility
    captured_at: datetime
    trace_id: str

    def __post_init__(self) -> None:
        for name in ("verification_id", "blind_request_id", "relation_request_id", "trace_id"):
            require_identifier(getattr(self, name), name)
        if self.blind_request_id == self.relation_request_id:
            raise ValueError("A/B request IDは別でなければなりません")
        if not isinstance(self.semantic_plan, SpeechSemanticPlan):
            raise ValueError("semantic_plan が不正です")
        if not isinstance(self.utterance, CharacterUtterance):
            raise ValueError("utterance が不正です")
        if not isinstance(self.llm_priority, LLMPriority):
            raise ValueError("llm_priority が不正です")
        if not isinstance(self.interruptibility, LLMInterruptibility):
            raise ValueError("interruptibility が不正です")
        require_aware(self.captured_at, "captured_at")
        if utc_instant(self.captured_at) < max(
            utc_instant(self.semantic_plan.committed_at),
            utc_instant(self.utterance.committed_at),
        ):
            raise ValueError("snapshotは入力commitより前にできません")
        self._validate_pair()

    @property
    def revisions(self) -> RevisionVector:
        return self.semantic_plan.candidate.revisions

    @property
    def source_event_ids(self) -> tuple[str, ...]:
        return self.semantic_plan.candidate.source_event_ids

    def _validate_pair(self) -> None:
        plan = self.semantic_plan
        utterance = self.utterance.candidate
        if (
            utterance.semantic_plan_id != plan.plan_id
            or utterance.source_decision_id != plan.candidate.decision_id
            or utterance.source_intent_id != plan.candidate.intent_id
            or utterance.source_event_ids != plan.candidate.source_event_ids
            or utterance.revisions != plan.candidate.revisions
        ):
            raise ValueError("Plan / Utterance pair provenanceが一致しません")

    def pair_dict(self) -> dict[str, object]:
        return {
            "verification_id": self.verification_id,
            "semantic_plan_id": self.semantic_plan.plan_id,
            "utterance_id": self.utterance.utterance_id,
            "source_decision_id": self.semantic_plan.candidate.decision_id,
            "source_intent_id": self.semantic_plan.candidate.intent_id,
            "source_event_ids": list(self.source_event_ids),
            "revisions": self.revisions.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SemanticVerificationEligibilityView:
    semantic_plan_id: str
    utterance_id: str
    revisions: RevisionVector
    active: bool
    superseded: bool
    cancelled: bool

    def __post_init__(self) -> None:
        require_identifier(self.semantic_plan_id, "semantic_plan_id")
        require_identifier(self.utterance_id, "utterance_id")
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions が不正です")
        for name in ("active", "superseded", "cancelled"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} はboolでなければなりません")


@dataclass(frozen=True, slots=True)
class SemanticRelationObservation:
    observation_id: str
    verification_id: str
    blind_observation_id: str
    relation_observation_id: str
    semantic_plan_id: str
    utterance_id: str
    rejection_categories: tuple[SemanticRejectionCategory, ...]
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        for name in (
            "observation_id",
            "verification_id",
            "blind_observation_id",
            "relation_observation_id",
            "semantic_plan_id",
            "utterance_id",
        ):
            require_identifier(getattr(self, name), name)
        categories = _owned(
            self.rejection_categories,
            SemanticRejectionCategory,
            "rejection_categories",
        )
        if len(set(categories)) != len(categories):
            raise ValueError("rejection categoryは重複できません")
        object.__setattr__(self, "rejection_categories", categories)
        require_aware(self.committed_at, "committed_at")
        if _proof is not _OBSERVATION_PROOF:
            raise ValueError("SemanticRelationObservationはAuthority経由でのみ構築できます")


@dataclass(frozen=True, slots=True)
class SemanticAcceptance:
    acceptance_id: str
    observation_id: str
    semantic_plan_id: str
    utterance_id: str
    state: SemanticAcceptanceState
    rejection_categories: tuple[SemanticRejectionCategory, ...]
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        for name in ("acceptance_id", "observation_id", "semantic_plan_id", "utterance_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.state, SemanticAcceptanceState):
            raise ValueError("state が不正です")
        categories = _owned(
            self.rejection_categories,
            SemanticRejectionCategory,
            "rejection_categories",
        )
        if len(set(categories)) != len(categories):
            raise ValueError("rejection categoryは重複できません")
        if (self.state is SemanticAcceptanceState.ACCEPTED) != (not categories):
            raise ValueError("ACCEPTEDはrejection categoryを持てません")
        object.__setattr__(self, "rejection_categories", categories)
        require_aware(self.committed_at, "committed_at")
        if _proof is not _ACCEPTANCE_PROOF:
            raise ValueError("SemanticAcceptanceはAuthority経由でのみ構築できます")
