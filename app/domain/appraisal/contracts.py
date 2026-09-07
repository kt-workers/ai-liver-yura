from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    timestamp_to_json,
    utc_instant,
)


class StateFacetKind(str, Enum):
    EMOTION = "emotion"
    DESIRE = "desire"
    DRIVE = "drive"
    MOTIVATION = "motivation"
    VALUE = "value"
    INTEREST = "interest"
    RELATIONSHIP = "relationship"
    ENERGY = "energy"
    AROUSAL = "arousal"


class AppraisalPath(str, Enum):
    FAST_DETERMINISTIC = "fast_deterministic"
    DEEP_LLM = "deep_llm"
    DECAY = "decay"
    LIFECYCLE = "lifecycle"


class AppraisalDimensionKind(str, Enum):
    PLEASANTNESS = "pleasantness"
    NOVELTY = "novelty"
    GOAL_CONGRUENCE = "goal_congruence"
    CONTROLLABILITY = "controllability"
    CERTAINTY = "certainty"
    SOCIAL_MEANING = "social_meaning"


class LifecycleKind(str, Enum):
    STARTUP = "startup"
    RESUME = "resume"


class DecayTargetScope(str, Enum):
    GLOBAL = "global"
    TARGETED = "targeted"


class DecayDiagnosticCode(str, Enum):
    POLICY_RULE_MISSING = "DECAY_POLICY_RULE_MISSING"
    POLICY_UNAVAILABLE = "DECAY_POLICY_UNAVAILABLE"


def _number(value: float, name: str, *, minimum: float, maximum: float) -> None:
    if type(value) not in (int, float) or not isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _owned_ids(values: tuple[str, ...], name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    result = tuple(values)
    if non_empty and not result:
        raise ValueError(f"{name} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    return result


@dataclass(frozen=True, slots=True)
class FacetRef:
    kind: StateFacetKind
    state_key: str
    target_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StateFacetKind):
            raise ValueError("kind must be StateFacetKind")
        require_identifier(self.state_key, "state_key")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        if self.kind in (StateFacetKind.INTEREST, StateFacetKind.RELATIONSHIP):
            if self.target_ref is None:
                raise ValueError("interest and relationship facets require target_ref")

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "state_key": self.state_key, "target_ref": self.target_ref}


@dataclass(frozen=True, slots=True)
class InternalStateFacet:
    ref: FacetRef
    current: float
    previous: float
    last_delta: float
    confidence: float
    cause_refs: tuple[str, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.ref, FacetRef):
            raise ValueError("ref must be FacetRef")
        for name in ("current", "previous", "last_delta"):
            _number(getattr(self, name), name, minimum=-1.0, maximum=1.0)
        _number(self.confidence, "confidence", minimum=0.0, maximum=1.0)
        object.__setattr__(
            self, "cause_refs", _owned_ids(self.cause_refs, "cause_refs", non_empty=True)
        )
        require_aware(self.updated_at, "updated_at")
        if abs((self.current - self.previous) - self.last_delta) > 1e-9:
            raise ValueError("last_delta must equal current minus previous")

    def to_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref.to_dict(),
            "current": self.current,
            "previous": self.previous,
            "last_delta": self.last_delta,
            "confidence": self.confidence,
            "cause_refs": list(self.cause_refs),
            "updated_at": timestamp_to_json(self.updated_at),
        }


@dataclass(frozen=True, slots=True)
class InternalStateSnapshot:
    revision: int
    source_context_revision: int
    facets: tuple[InternalStateFacet, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        require_revision(self.revision, "revision")
        require_revision(self.source_context_revision, "source_context_revision")
        require_aware(self.updated_at, "updated_at")
        if not isinstance(self.facets, (list, tuple)):
            raise ValueError("facets must be an array")
        facets = tuple(self.facets)
        if any(not isinstance(item, InternalStateFacet) for item in facets):
            raise ValueError("facets must contain InternalStateFacet")
        refs = [item.ref for item in facets]
        if len(refs) != len(set(refs)):
            raise ValueError("state facet refs must be unique")
        if any(utc_instant(item.updated_at) > utc_instant(self.updated_at) for item in facets):
            raise ValueError("facet cannot be newer than snapshot")
        object.__setattr__(self, "facets", facets)

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "source_context_revision": self.source_context_revision,
            "facets": [item.to_dict() for item in self.facets],
            "updated_at": timestamp_to_json(self.updated_at),
        }


@dataclass(frozen=True, slots=True)
class AppraisalDimension:
    kind: AppraisalDimensionKind
    value: float
    target_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AppraisalDimensionKind):
            raise ValueError("kind must be AppraisalDimensionKind")
        _number(self.value, "value", minimum=-1.0, maximum=1.0)
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "value": self.value, "target_ref": self.target_ref}


@dataclass(frozen=True, slots=True)
class StateDeltaProposal:
    facet_ref: FacetRef
    delta: float
    confidence: float
    cause_refs: tuple[str, ...]
    decay_provenance: DecayProposalProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.facet_ref, FacetRef):
            raise ValueError("facet_ref must be FacetRef")
        _number(self.delta, "delta", minimum=-1.0, maximum=1.0)
        _number(self.confidence, "confidence", minimum=0.0, maximum=1.0)
        if self.delta == 0:
            raise ValueError("delta must not be zero")
        object.__setattr__(
            self, "cause_refs", _owned_ids(self.cause_refs, "cause_refs", non_empty=True)
        )
        if self.decay_provenance is not None and not isinstance(
            self.decay_provenance, DecayProposalProvenance
        ):
            raise ValueError("decay_provenance は DecayProposalProvenance でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "facet_ref": self.facet_ref.to_dict(),
            "delta": self.delta,
            "confidence": self.confidence,
            "cause_refs": list(self.cause_refs),
            "decay_provenance": None
            if self.decay_provenance is None
            else self.decay_provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class DecayProposalProvenance:
    """減衰候補を生成した方針・規則・世代・時刻の由来。"""

    decay_policy_id: str
    decay_policy_revision: int
    decay_rule_id: str
    base_state_revision: int
    source_context_revision: int
    elapsed_seconds: float
    evaluated_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.decay_policy_id, "decay_policy_id")
        require_revision(self.decay_policy_revision, "decay_policy_revision")
        require_identifier(self.decay_rule_id, "decay_rule_id")
        require_revision(self.base_state_revision, "base_state_revision")
        require_revision(self.source_context_revision, "source_context_revision")
        if (
            type(self.elapsed_seconds) not in (int, float)
            or not isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("elapsed_seconds は有限な0以上でなければなりません")
        object.__setattr__(self, "elapsed_seconds", float(self.elapsed_seconds))
        require_aware(self.evaluated_at, "evaluated_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "decay_policy_id": self.decay_policy_id,
            "decay_policy_revision": self.decay_policy_revision,
            "decay_rule_id": self.decay_rule_id,
            "base_state_revision": self.base_state_revision,
            "source_context_revision": self.source_context_revision,
            "elapsed_seconds": self.elapsed_seconds,
            "evaluated_at": timestamp_to_json(self.evaluated_at),
        }


@dataclass(frozen=True, slots=True)
class DecayDiagnostic:
    code: DecayDiagnosticCode
    facet_ref: FacetRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, DecayDiagnosticCode):
            raise ValueError("code は DecayDiagnosticCode でなければなりません")
        if self.facet_ref is not None and not isinstance(self.facet_ref, FacetRef):
            raise ValueError("facet_ref は FacetRef でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "facet_ref": None if self.facet_ref is None else self.facet_ref.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AppraisalCandidate:
    candidate_id: str
    source_event_ids: tuple[str, ...]
    source_context_revision: int
    base_state_revision: int
    path: AppraisalPath
    dimensions: tuple[AppraisalDimension, ...]
    proposals: tuple[StateDeltaProposal, ...]
    salience: float
    relevance: float
    evidence_refs: tuple[str, ...]
    created_at: datetime
    diagnostics: tuple[DecayDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.candidate_id, "candidate_id")
        if not isinstance(self.path, AppraisalPath):
            raise ValueError("path must be AppraisalPath")
        require_revision(self.source_context_revision, "source_context_revision")
        require_revision(self.base_state_revision, "base_state_revision")
        object.__setattr__(
            self,
            "source_event_ids",
            _owned_ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        object.__setattr__(self, "evidence_refs", _owned_ids(self.evidence_refs, "evidence_refs"))
        if not isinstance(self.dimensions, (list, tuple)):
            raise ValueError("dimensions must be an array")
        if not isinstance(self.proposals, (list, tuple)):
            raise ValueError("proposals must be an array")
        dimensions, proposals = tuple(self.dimensions), tuple(self.proposals)
        if any(not isinstance(item, AppraisalDimension) for item in dimensions):
            raise ValueError("dimensions must contain AppraisalDimension")
        if any(not isinstance(item, StateDeltaProposal) for item in proposals):
            raise ValueError("proposals must contain StateDeltaProposal")
        dimension_refs = [(item.kind, item.target_ref) for item in dimensions]
        if len(dimension_refs) != len(set(dimension_refs)):
            raise ValueError("appraisal dimensions must be unique")
        proposal_refs = [item.facet_ref for item in proposals]
        if len(proposal_refs) != len(set(proposal_refs)):
            raise ValueError("state delta proposal refs must be unique")
        object.__setattr__(self, "dimensions", dimensions)
        object.__setattr__(self, "proposals", proposals)
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, DecayDiagnostic) for item in diagnostics):
            raise ValueError("diagnostics は DecayDiagnostic を含まなければなりません")
        if self.path in (AppraisalPath.DECAY, AppraisalPath.LIFECYCLE):
            if any(item.decay_provenance is None for item in proposals):
                raise ValueError("減衰候補にはdecay provenanceが必要です")
        object.__setattr__(self, "diagnostics", diagnostics)
        _number(self.salience, "salience", minimum=0.0, maximum=1.0)
        _number(self.relevance, "relevance", minimum=0.0, maximum=1.0)
        require_aware(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "source_event_ids": list(self.source_event_ids),
            "source_context_revision": self.source_context_revision,
            "base_state_revision": self.base_state_revision,
            "path": self.path.value,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "proposals": [item.to_dict() for item in self.proposals],
            "salience": self.salience,
            "relevance": self.relevance,
            "evidence_refs": list(self.evidence_refs),
            "created_at": timestamp_to_json(self.created_at),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


_MAX_APPRAISAL_EVIDENCE_REFS = 16


@dataclass(frozen=True, slots=True)
class AppraisalFactsSnapshot:
    revision: int
    source_context_revision: int
    internal_state_revision: int
    source_event_ids: tuple[str, ...]
    dimensions: tuple[AppraisalDimension, ...]
    salience: float
    relevance: float
    evidence_refs: tuple[str, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        for name in ("revision", "source_context_revision", "internal_state_revision"):
            require_revision(getattr(self, name), name)
        object.__setattr__(
            self,
            "source_event_ids",
            _owned_ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        if not isinstance(self.dimensions, (list, tuple)):
            raise ValueError("dimensions must be an array")
        dimensions = tuple(self.dimensions)
        if any(not isinstance(item, AppraisalDimension) for item in dimensions):
            raise ValueError("dimensions must contain AppraisalDimension")
        if len({(item.kind, item.target_ref) for item in dimensions}) != len(dimensions):
            raise ValueError("appraisal dimensions must be unique")
        object.__setattr__(self, "dimensions", dimensions)
        _number(self.salience, "salience", minimum=0.0, maximum=1.0)
        _number(self.relevance, "relevance", minimum=0.0, maximum=1.0)
        evidence_refs = _owned_ids(self.evidence_refs, "evidence_refs")
        if len(evidence_refs) > _MAX_APPRAISAL_EVIDENCE_REFS:
            raise ValueError("evidence_refs exceeds the bounded maximum")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        require_aware(self.captured_at, "captured_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "source_context_revision": self.source_context_revision,
            "internal_state_revision": self.internal_state_revision,
            "source_event_ids": list(self.source_event_ids),
            "dimensions": [item.to_dict() for item in self.dimensions],
            "salience": self.salience,
            "relevance": self.relevance,
            "evidence_refs": list(self.evidence_refs),
            "captured_at": timestamp_to_json(self.captured_at),
        }


def freeze_appraisal_facts(
    candidate: AppraisalCandidate,
    state: InternalStateSnapshot,
    *,
    revision: int,
    captured_at: datetime,
) -> AppraisalFactsSnapshot:
    if not isinstance(candidate, AppraisalCandidate) or not isinstance(
        state, InternalStateSnapshot
    ):
        raise ValueError("candidate and state must be appraisal contracts")
    if candidate.source_context_revision != state.source_context_revision:
        raise ValueError("candidate context revision must match state")
    if candidate.base_state_revision != state.revision:
        raise ValueError("candidate state revision must match state")
    if utc_instant(candidate.created_at) > utc_instant(captured_at):
        raise ValueError("facts cannot predate candidate")
    return AppraisalFactsSnapshot(
        revision,
        candidate.source_context_revision,
        state.revision,
        candidate.source_event_ids,
        candidate.dimensions,
        candidate.salience,
        candidate.relevance,
        candidate.evidence_refs,
        captured_at,
    )


@dataclass(frozen=True, slots=True)
class DecayFacetRule:
    rule_id: str
    facet_kind: StateFacetKind
    state_key: str | None
    target_scope: DecayTargetScope
    neutral_baseline: float
    half_life_seconds: float
    minimum_elapsed_seconds: float

    def __post_init__(self) -> None:
        require_identifier(self.rule_id, "rule_id")
        if not isinstance(self.facet_kind, StateFacetKind):
            raise ValueError("facet_kind は StateFacetKind でなければなりません")
        if self.state_key is not None:
            require_identifier(self.state_key, "state_key")
        if not isinstance(self.target_scope, DecayTargetScope):
            raise ValueError("target_scope は DecayTargetScope でなければなりません")
        _number(self.neutral_baseline, "neutral_baseline", minimum=-1.0, maximum=1.0)
        if (
            type(self.half_life_seconds) not in (int, float)
            or not isfinite(self.half_life_seconds)
            or self.half_life_seconds <= 0
        ):
            raise ValueError("half_life_seconds は有限の正数でなければなりません")
        if (
            type(self.minimum_elapsed_seconds) not in (int, float)
            or not isfinite(self.minimum_elapsed_seconds)
            or self.minimum_elapsed_seconds < 0
        ):
            raise ValueError("minimum_elapsed_seconds は有限な0以上でなければなりません")
        object.__setattr__(self, "neutral_baseline", float(self.neutral_baseline))
        object.__setattr__(self, "half_life_seconds", float(self.half_life_seconds))
        object.__setattr__(self, "minimum_elapsed_seconds", float(self.minimum_elapsed_seconds))


@dataclass(frozen=True, slots=True)
class DecayPolicy:
    policy_id: str
    policy_revision: int
    rules: tuple[DecayFacetRule, ...]

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        rules = tuple(self.rules)
        if any(not isinstance(item, DecayFacetRule) for item in rules):
            raise ValueError("rules は DecayFacetRule を含まなければなりません")
        if len({item.rule_id for item in rules}) != len(rules):
            raise ValueError("rule_id は一意でなければなりません")
        identities = {(item.facet_kind, item.state_key, item.target_scope) for item in rules}
        if len(identities) != len(rules):
            raise ValueError("減衰規則の選択条件は重複できません")
        object.__setattr__(self, "rules", rules)


@dataclass(frozen=True, slots=True)
class LifecycleAppraisalInput:
    event_id: str
    kind: LifecycleKind
    source_context_revision: int
    occurred_at: datetime
    downtime_seconds: float

    def __post_init__(self) -> None:
        require_identifier(self.event_id, "event_id")
        if not isinstance(self.kind, LifecycleKind):
            raise ValueError("kind must be LifecycleKind")
        require_revision(self.source_context_revision, "source_context_revision")
        require_aware(self.occurred_at, "occurred_at")
        if (
            type(self.downtime_seconds) not in (int, float)
            or not isfinite(self.downtime_seconds)
            or self.downtime_seconds < 0
        ):
            raise ValueError("downtime_seconds must be a non-negative finite number")
