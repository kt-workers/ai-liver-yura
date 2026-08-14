from __future__ import annotations

from collections.abc import Mapping
from dataclasses import InitVar, dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import TypeVar, cast

from app.domain.contracts import ExecutionStatus, RevisionVector
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    thaw_json,
    timestamp_to_json,
    utc_instant,
)
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveIntent,
    ExecutiveIntentKind,
    SpeechIntentPayload,
)


class SpeechSemanticFactKind(str, Enum):
    GENERAL = "general"
    EXECUTION = "execution"
    RELATIONSHIP = "relationship"
    DISCOURSE = "discourse"
    SELF = "self"


class SemanticClaimKind(str, Enum):
    GENERAL = "general"
    EXECUTION_STATUS = "execution_status"


class SpeechPropositionDisposition(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


class SemanticPolarity(str, Enum):
    AFFIRM = "affirm"
    NEGATE = "negate"
    UNKNOWN = "unknown"


class SemanticCertainty(str, Enum):
    CERTAIN = "certain"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"


class SelfDisclosurePolicy(str, Enum):
    FORBIDDEN = "forbidden"
    FACT_GROUNDED = "fact_grounded"
    ALLOWED = "allowed"


class SpeechTruthRule(str, Enum):
    REQUIRE_MATCH = "require_match"
    PRESERVE_UNKNOWN = "preserve_unknown"
    FORBID_COMPLETION_CLAIM = "forbid_completion_claim"


T = TypeVar("T")
_PLAN_PROOF = object()


def _owned(values: object, expected: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    result = tuple(values)
    if any(not isinstance(item, expected) for item in result):
        raise ValueError(f"{name} contains an invalid value")
    return cast(tuple[T, ...], result)


def _ids(values: object, name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    result = _owned(values, str, name)
    if any(not item.strip() for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    if non_empty and not result:
        raise ValueError(f"{name} must not be empty")
    return result


@dataclass(frozen=True, slots=True)
class SpeechSemanticFact:
    fact_id: str
    kind: SpeechSemanticFactKind
    subject_ref: str
    predicate: str
    value: JsonValue
    claim_kind: SemanticClaimKind = SemanticClaimKind.GENERAL
    execution_status: ExecutionStatus | None = None
    polarity: SemanticPolarity = SemanticPolarity.AFFIRM
    certainty: SemanticCertainty = SemanticCertainty.CERTAIN
    degree: float | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.fact_id, "fact_id")
        if not isinstance(self.kind, SpeechSemanticFactKind):
            raise ValueError("kind must be SpeechSemanticFactKind")
        require_identifier(self.subject_ref, "subject_ref")
        require_identifier(self.predicate, "predicate")
        object.__setattr__(self, "value", _semantic_value(self.value))
        _validate_semantic_facets(
            self.claim_kind,
            self.execution_status,
            self.polarity,
            self.certainty,
            self.degree,
        )
        if (self.kind is SpeechSemanticFactKind.EXECUTION) != (
            self.claim_kind is SemanticClaimKind.EXECUTION_STATUS
        ):
            raise ValueError("execution fact kind must match execution claim kind")
        object.__setattr__(self, "evidence_refs", _ids(self.evidence_refs, "evidence_refs"))

    def to_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind.value,
            "subject_ref": self.subject_ref,
            "predicate": self.predicate,
            "value": thaw_json(self.value),
            "claim_kind": self.claim_kind.value,
            "execution_status": None
            if self.execution_status is None
            else self.execution_status.value,
            "polarity": self.polarity.value,
            "certainty": self.certainty.value,
            "degree": self.degree,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class SpeechProposition:
    proposition_id: str
    subject_ref: str
    predicate: str
    value: JsonValue
    disposition: SpeechPropositionDisposition
    polarity: SemanticPolarity
    certainty: SemanticCertainty
    evidence_fact_refs: tuple[str, ...]
    degree: float | None = None
    claim_kind: SemanticClaimKind = SemanticClaimKind.GENERAL
    execution_status: ExecutionStatus | None = None

    def __post_init__(self) -> None:
        require_identifier(self.proposition_id, "proposition_id")
        require_identifier(self.subject_ref, "subject_ref")
        require_identifier(self.predicate, "predicate")
        object.__setattr__(self, "value", _semantic_value(self.value))
        for name, expected in (
            ("disposition", SpeechPropositionDisposition),
            ("polarity", SemanticPolarity),
            ("certainty", SemanticCertainty),
        ):
            if not isinstance(getattr(self, name), expected):
                raise ValueError(f"{name} has an invalid value")
        object.__setattr__(
            self,
            "evidence_fact_refs",
            _ids(self.evidence_fact_refs, "evidence_fact_refs", non_empty=True),
        )
        _validate_semantic_facets(
            self.claim_kind,
            self.execution_status,
            self.polarity,
            self.certainty,
            self.degree,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "proposition_id": self.proposition_id,
            "subject_ref": self.subject_ref,
            "predicate": self.predicate,
            "value": thaw_json(self.value),
            "disposition": self.disposition.value,
            "polarity": self.polarity.value,
            "certainty": self.certainty.value,
            "degree": self.degree,
            "claim_kind": self.claim_kind.value,
            "execution_status": None
            if self.execution_status is None
            else self.execution_status.value,
            "evidence_fact_refs": list(self.evidence_fact_refs),
        }


@dataclass(frozen=True, slots=True)
class SpeechTruthConstraint:
    constraint_id: str
    fact_ref: str
    rule: SpeechTruthRule

    def __post_init__(self) -> None:
        require_identifier(self.constraint_id, "constraint_id")
        require_identifier(self.fact_ref, "fact_ref")
        if not isinstance(self.rule, SpeechTruthRule):
            raise ValueError("rule must be SpeechTruthRule")

    def to_dict(self) -> dict[str, str]:
        return {
            "constraint_id": self.constraint_id,
            "fact_ref": self.fact_ref,
            "rule": self.rule.value,
        }


@dataclass(frozen=True, slots=True)
class DeterministicSpeechDirective:
    propositions: tuple[SpeechProposition, ...]
    self_disclosure: SelfDisclosurePolicy
    question_budget: int
    new_direction_budget: int
    truth_constraint_refs: tuple[str, ...]
    relationship_constraint_refs: tuple[str, ...] = ()
    discourse_constraint_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "propositions", _owned(self.propositions, SpeechProposition, "propositions")
        )
        if not self.propositions:
            raise ValueError("propositions must not be empty")
        if len({item.proposition_id for item in self.propositions}) != len(self.propositions):
            raise ValueError("proposition ids must be unique")
        if not isinstance(self.self_disclosure, SelfDisclosurePolicy):
            raise ValueError("self_disclosure must be SelfDisclosurePolicy")
        for name in ("question_budget", "new_direction_budget"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        for name in (
            "truth_constraint_refs",
            "relationship_constraint_refs",
            "discourse_constraint_refs",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        all_constraint_refs = (
            self.truth_constraint_refs
            + self.relationship_constraint_refs
            + self.discourse_constraint_refs
        )
        if len(all_constraint_refs) != len(set(all_constraint_refs)):
            raise ValueError("all directive constraint refs must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "propositions": [item.to_dict() for item in self.propositions],
            "self_disclosure": self.self_disclosure.value,
            "question_budget": self.question_budget,
            "new_direction_budget": self.new_direction_budget,
            "truth_constraint_refs": list(self.truth_constraint_refs),
            "relationship_constraint_refs": list(self.relationship_constraint_refs),
            "discourse_constraint_refs": list(self.discourse_constraint_refs),
        }


@dataclass(frozen=True, slots=True)
class SpeechSemanticContextSnapshot:
    decision: CommittedExecutiveDecision
    intent_id: str
    facts: tuple[SpeechSemanticFact, ...]
    truth_constraints: tuple[SpeechTruthConstraint, ...]
    available_constraint_refs: tuple[str, ...]
    self_disclosure_policy: SelfDisclosurePolicy
    max_question_budget: int
    max_new_direction_budget: int
    captured_at: datetime
    deterministic_directive: DeterministicSpeechDirective | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, CommittedExecutiveDecision):
            raise ValueError("decision must be CommittedExecutiveDecision")
        require_identifier(self.intent_id, "intent_id")
        facts = _owned(self.facts, SpeechSemanticFact, "facts")
        constraints = _owned(self.truth_constraints, SpeechTruthConstraint, "truth_constraints")
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "truth_constraints", constraints)
        for values, attribute, name in (
            (facts, "fact_id", "fact ids"),
            (constraints, "constraint_id", "truth constraint ids"),
        ):
            identifiers = [getattr(item, attribute) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} must be unique")
        available = _ids(self.available_constraint_refs, "available_constraint_refs")
        object.__setattr__(self, "available_constraint_refs", available)
        if not isinstance(self.self_disclosure_policy, SelfDisclosurePolicy):
            raise ValueError("self_disclosure_policy must be SelfDisclosurePolicy")
        for name in ("max_question_budget", "max_new_direction_budget"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        require_aware(self.captured_at, "captured_at")
        if utc_instant(self.captured_at) < utc_instant(self.decision.committed_at):
            raise ValueError("snapshot cannot predate committed decision")
        intent = self.intent
        fact_ids = {item.fact_id for item in facts}
        constraint_ids = {item.constraint_id for item in constraints}
        if any(item.fact_ref not in fact_ids for item in constraints):
            raise ValueError("truth constraint fact is outside bounded facts")
        payload = cast(SpeechIntentPayload, intent.payload)
        grounded_facts = (
            (payload.semantic_goal_ref,)
            + (() if payload.target_ref is None else (payload.target_ref,))
            + intent.evidence_refs
            + intent.forbidden_claim_refs
        )
        if any(item not in fact_ids for item in grounded_facts):
            raise ValueError("speech intent fact reference is outside snapshot")
        allowed_constraints = set(available) | constraint_ids
        if any(item not in allowed_constraints for item in payload.constraint_refs):
            raise ValueError("speech intent constraint is outside snapshot")
        if self.deterministic_directive is not None:
            if not isinstance(self.deterministic_directive, DeterministicSpeechDirective):
                raise ValueError("deterministic_directive has an invalid type")
            self._validate_directive_refs(self.deterministic_directive)

    @property
    def intent(self) -> ExecutiveIntent:
        matches = [
            item for item in self.decision.candidate.intents if item.intent_id == self.intent_id
        ]
        if len(matches) != 1:
            raise ValueError("speech intent does not belong to decision")
        intent = matches[0]
        if intent.kind is not ExecutiveIntentKind.SPEECH or not isinstance(
            intent.payload, SpeechIntentPayload
        ):
            raise ValueError("intent must be a speech intent")
        return intent

    @property
    def revisions(self) -> RevisionVector:
        candidate = self.decision.candidate
        return RevisionVector(
            candidate.source_context_revision,
            candidate.goal_revision,
            candidate.attention_revision,
        )

    @property
    def source_event_ids(self) -> tuple[str, ...]:
        return self.decision.candidate.source_event_ids

    def _validate_directive_refs(self, directive: DeterministicSpeechDirective) -> None:
        fact_ids = {item.fact_id for item in self.facts}
        if any(
            ref not in fact_ids
            for proposition in directive.propositions
            for ref in proposition.evidence_fact_refs
        ):
            raise ValueError("directive proposition evidence is outside snapshot")
        truth_ids = {item.constraint_id for item in self.truth_constraints}
        if set(directive.truth_constraint_refs) != truth_ids:
            raise ValueError("directive truth constraints must match authoritative constraints")
        allowed = set(self.available_constraint_refs)
        if any(
            ref not in allowed
            for refs in (
                directive.relationship_constraint_refs,
                directive.discourse_constraint_refs,
            )
            for ref in refs
        ):
            raise ValueError("directive constraint is outside snapshot")
        if directive.question_budget > self.max_question_budget:
            raise ValueError("directive question budget exceeds authoritative maximum")
        if directive.new_direction_budget > self.max_new_direction_budget:
            raise ValueError("directive new direction budget exceeds authoritative maximum")
        _validate_self_disclosure_policy(directive.self_disclosure, self.self_disclosure_policy)

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision.decision_id,
            "intent": self.intent.to_dict(),
            "source_event_ids": list(self.source_event_ids),
            "revisions": self.revisions.to_dict(),
            "facts": [item.to_dict() for item in self.facts],
            "truth_constraints": [item.to_dict() for item in self.truth_constraints],
            "available_constraint_refs": list(self.available_constraint_refs),
            "self_disclosure_policy": self.self_disclosure_policy.value,
            "max_question_budget": self.max_question_budget,
            "max_new_direction_budget": self.max_new_direction_budget,
            "captured_at": timestamp_to_json(self.captured_at),
            "deterministic_directive": None
            if self.deterministic_directive is None
            else self.deterministic_directive.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SpeechSemanticCandidate:
    candidate_id: str
    decision_id: str
    intent_id: str
    source_event_ids: tuple[str, ...]
    revisions: RevisionVector
    propositions: tuple[SpeechProposition, ...]
    self_disclosure: SelfDisclosurePolicy
    question_budget: int
    new_direction_budget: int
    truth_constraint_refs: tuple[str, ...]
    relationship_constraint_refs: tuple[str, ...]
    discourse_constraint_refs: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("candidate_id", "decision_id", "intent_id"):
            require_identifier(getattr(self, name), name)
        object.__setattr__(
            self,
            "source_event_ids",
            _ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions must be RevisionVector")
        directive = DeterministicSpeechDirective(
            self.propositions,
            self.self_disclosure,
            self.question_budget,
            self.new_direction_budget,
            self.truth_constraint_refs,
            self.relationship_constraint_refs,
            self.discourse_constraint_refs,
        )
        object.__setattr__(self, "propositions", directive.propositions)
        for name in (
            "truth_constraint_refs",
            "relationship_constraint_refs",
            "discourse_constraint_refs",
        ):
            object.__setattr__(self, name, getattr(directive, name))
        require_aware(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "decision_id": self.decision_id,
            "intent_id": self.intent_id,
            "source_event_ids": list(self.source_event_ids),
            "revisions": self.revisions.to_dict(),
            "propositions": [item.to_dict() for item in self.propositions],
            "self_disclosure": self.self_disclosure.value,
            "question_budget": self.question_budget,
            "new_direction_budget": self.new_direction_budget,
            "truth_constraint_refs": list(self.truth_constraint_refs),
            "relationship_constraint_refs": list(self.relationship_constraint_refs),
            "discourse_constraint_refs": list(self.discourse_constraint_refs),
            "created_at": timestamp_to_json(self.created_at),
        }


@dataclass(frozen=True, slots=True)
class SpeechSemanticPlan:
    plan_id: str
    candidate: SpeechSemanticCandidate
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        require_identifier(self.plan_id, "plan_id")
        if not isinstance(self.candidate, SpeechSemanticCandidate):
            raise ValueError("candidate must be SpeechSemanticCandidate")
        require_aware(self.committed_at, "committed_at")
        if utc_instant(self.committed_at) < utc_instant(self.candidate.created_at):
            raise ValueError("committed_at cannot predate candidate")
        if _proof is not _PLAN_PROOF:
            raise ValueError("plan construction requires SpeechSemanticAuthority")

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "candidate": self.candidate.to_dict(),
            "committed_at": timestamp_to_json(self.committed_at),
        }


def _validate_self_disclosure_policy(
    candidate: SelfDisclosurePolicy, authoritative: SelfDisclosurePolicy
) -> None:
    allowed = {
        SelfDisclosurePolicy.FORBIDDEN: {SelfDisclosurePolicy.FORBIDDEN},
        SelfDisclosurePolicy.FACT_GROUNDED: {
            SelfDisclosurePolicy.FORBIDDEN,
            SelfDisclosurePolicy.FACT_GROUNDED,
        },
        SelfDisclosurePolicy.ALLOWED: set(SelfDisclosurePolicy),
    }
    if candidate not in allowed[authoritative]:
        raise ValueError("self disclosure policy exceeds authoritative policy")


def _semantic_value(value: JsonValue) -> JsonValue:
    frozen = freeze_json(value)
    if isinstance(frozen, Mapping) and "degree" in frozen:
        raise ValueError("semantic value cannot duplicate the degree field")
    return frozen


def _validate_semantic_facets(
    claim_kind: SemanticClaimKind,
    execution_status: ExecutionStatus | None,
    polarity: SemanticPolarity,
    certainty: SemanticCertainty,
    degree: float | None,
) -> None:
    if not isinstance(claim_kind, SemanticClaimKind):
        raise ValueError("claim_kind must be SemanticClaimKind")
    if (claim_kind is SemanticClaimKind.EXECUTION_STATUS) != (execution_status is not None):
        raise ValueError("execution status must match execution claim kind")
    if execution_status is not None and not isinstance(execution_status, ExecutionStatus):
        raise ValueError("execution_status must be ExecutionStatus")
    if not isinstance(polarity, SemanticPolarity):
        raise ValueError("polarity must be SemanticPolarity")
    if not isinstance(certainty, SemanticCertainty):
        raise ValueError("certainty must be SemanticCertainty")
    if degree is not None and (
        type(degree) not in (int, float) or not isfinite(degree) or not 0 <= degree <= 1
    ):
        raise ValueError("degree must be a finite number between zero and one")
