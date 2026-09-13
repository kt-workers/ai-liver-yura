"""明示したOwner公開と方針だけから発話意味文脈を構成する。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TypeAlias

from app.domain.activity_execution.contracts import (
    ActivityExecutionRecord,
    ExecutionEffectUncertainty,
)
from app.domain.attention.contracts import AttentionFocusView
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import ExecutionStatus, RevisionVector
from app.domain.contracts.common import require_identifier, require_revision
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityGenerationToken,
    AuthorityReadPublication,
    authority_mutation,
)
from app.domain.executive.contracts import CommittedExecutiveDecision
from app.domain.executive.speech_references import (
    ExecutiveSpeechReferenceResolution,
    ExecutiveSpeechReferenceRole,
    ExecutiveSpeechResolutionKind,
    ExecutiveSpeechSourceBinding,
    validate_resolution_keys,
)
from app.domain.goals.contracts import CommitmentState, GoalState
from app.domain.memory.contracts import MemoryRecord
from app.domain.speech_semantics_vocabulary import (
    CommunicativeGoalCatalogView,
    CommunicativeSubjectBinding,
    CommunicativeTargetMode,
    SemanticCertainty,
    SemanticClaimKind,
    SemanticPolarity,
    SpeechSemanticContextError,
    SpeechSemanticContextFailureCode,
    SpeechSemanticFactKind,
    SpeechSemanticMeaningPolicy,
    SpeechSourceContractKind,
    SpeechTruthRule,
    require_meaning_policy,
)

from .contracts import (
    DeterministicSpeechDirective,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechTruthConstraint,
)


@dataclass(frozen=True, slots=True)
class SpeechSemanticConstraintSource:
    source_id: str
    revision: int
    constraint: SpeechTruthConstraint

    def __post_init__(self) -> None:
        require_identifier(self.source_id, "source_id")
        require_revision(self.revision, "revision")
        if not isinstance(self.constraint, SpeechTruthConstraint):
            raise ValueError("制約の型が不正です")


SourceValue: TypeAlias = (
    GoalState
    | CommitmentState
    | ActivityExecutionRecord
    | MemoryRecord
    | AttentionFocusView
    | SpeechSemanticConstraintSource
)
C = SpeechSemanticContextFailureCode


@dataclass(frozen=True, slots=True)
class SpeechSemanticSourceRegistration:
    source_owner: str
    source_contract: SpeechSourceContractKind
    read: Callable[[str], AuthorityReadPublication[SourceValue] | None]

    def __post_init__(self) -> None:
        require_identifier(self.source_owner, "source_owner")
        if not isinstance(self.source_contract, SpeechSourceContractKind) or not callable(
            self.read
        ):
            raise ValueError("source登録の型が不正です")


@dataclass(frozen=True, slots=True)
class SpeechSemanticSourceBinding:
    resolution: ExecutiveSpeechReferenceResolution
    value: SourceValue
    tokens: tuple[AuthorityGenerationToken, ...]


_TYPES: dict[SpeechSourceContractKind, type[SourceValue]] = {
    SpeechSourceContractKind.GOAL: GoalState,
    SpeechSourceContractKind.COMMITMENT: CommitmentState,
    SpeechSourceContractKind.EXECUTION: ActivityExecutionRecord,
    SpeechSourceContractKind.MEMORY: MemoryRecord,
    SpeechSourceContractKind.ATTENTION: AttentionFocusView,
    SpeechSourceContractKind.TRUTH_CONSTRAINT: SpeechSemanticConstraintSource,
}


class SpeechSemanticContextSourcePort:
    def __init__(self, registrations: tuple[SpeechSemanticSourceRegistration, ...]) -> None:
        if type(registrations) is not tuple or any(
            not isinstance(x, SpeechSemanticSourceRegistration) for x in registrations
        ):
            raise ValueError("明示したsource登録tupleが必要です")
        self._registrations = {(x.source_owner, x.source_contract): x for x in registrations}
        if len(self._registrations) != len(registrations):
            raise ValueError("source登録が重複しています")

    def resolve(
        self, resolution: ExecutiveSpeechReferenceResolution
    ) -> SpeechSemanticSourceBinding:
        source = resolution.source
        if source is None:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        registration = self._registrations.get((source.source_owner, source.source_contract_kind))
        if registration is None:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        publication = registration.read(source.source_identity)
        if publication is None:
            raise SpeechSemanticContextError(C.SOURCE_NOT_FOUND)
        value = publication.value
        if type(value) is not _TYPES[source.source_contract_kind]:
            raise SpeechSemanticContextError(C.SOURCE_KIND_MISMATCH)
        identity, revision = _source_identity(value, source)
        if identity != source.source_identity:
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
        if revision != source.source_revision:
            raise SpeechSemanticContextError(C.SOURCE_REVISION_MISMATCH)
        if not publication.tokens:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        if any(t.owner_identity != source.source_owner for t in publication.tokens):
            raise SpeechSemanticContextError(C.SOURCE_OWNER_MISMATCH)
        if source.source_tokens and publication.tokens != source.source_tokens:
            raise SpeechSemanticContextError(C.CONTEXT_STALE)
        for token in publication.tokens:
            if token._participant.token() != token:
                raise SpeechSemanticContextError(C.CONTEXT_STALE)
        return SpeechSemanticSourceBinding(resolution, value, publication.tokens)


def _source_identity(value: SourceValue, source: ExecutiveSpeechSourceBinding) -> tuple[str, int]:
    if isinstance(value, GoalState):
        return value.goal_id, value.revision
    if isinstance(value, CommitmentState):
        return value.commitment_id, value.revision
    if isinstance(value, ActivityExecutionRecord):
        return value.invocation.command.command_id, value.record_revision
    if isinstance(value, MemoryRecord):
        return value.memory_id, value.revision
    if isinstance(value, AttentionFocusView):
        return source.source_identity, value.revision
    return value.source_id, value.revision


@dataclass(frozen=True, slots=True)
class SpeechSemanticFactProjectionRule:
    source_contract: SpeechSourceContractKind
    project: Callable[[SourceValue, ExecutiveSpeechReferenceResolution], SpeechSemanticFact]
    matches: Callable[[SourceValue], bool]

    def __post_init__(self) -> None:
        if not isinstance(self.source_contract, SpeechSourceContractKind) or not callable(
            self.project
        ):
            raise ValueError("投影規則が不正です")


@dataclass(frozen=True, slots=True)
class SpeechSemanticFactProjectionPolicy:
    policy_id: str
    revision: int
    rules: tuple[SpeechSemanticFactProjectionRule, ...]

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.revision, "revision")
        if type(self.rules) is not tuple or any(
            not isinstance(x, SpeechSemanticFactProjectionRule) for x in self.rules
        ):
            raise ValueError("投影規則は不変tupleでなければなりません")


class SpeechSemanticFactProjector:
    def __init__(self, policy: SpeechSemanticFactProjectionPolicy) -> None:
        self.policy = policy

    def project(self, binding: SpeechSemanticSourceBinding) -> SpeechSemanticFact:
        source = binding.resolution.source
        assert source is not None
        rules = [
            r
            for r in self.policy.rules
            if r.source_contract is source.source_contract_kind and r.matches(binding.value)
        ]
        if len(rules) != 1:
            raise SpeechSemanticContextError(C.UNSUPPORTED_PROJECTION)
        fact = rules[0].project(binding.value, binding.resolution)
        if (
            not isinstance(fact, SpeechSemanticFact)
            or fact.fact_id != binding.resolution.selected_ref
        ):
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
        if isinstance(binding.value, ActivityExecutionRecord):
            if (
                binding.value.effect_uncertainty is not ExecutionEffectUncertainty.NONE
                and fact.polarity is SemanticPolarity.NEGATE
            ):
                raise SpeechSemanticContextError(C.UNSUPPORTED_PROJECTION)
            if (
                fact.claim_kind is not SemanticClaimKind.EXECUTION_STATUS
                or fact.execution_status is not binding.value.result.status
            ):
                raise SpeechSemanticContextError(C.UNSUPPORTED_PROJECTION)
        return fact


@dataclass(frozen=True, slots=True)
class SpeechTruthConstraintProjectionRule:
    fact_kind: SpeechSemanticFactKind
    claim_kind: SemanticClaimKind
    execution_status: ExecutionStatus | None
    polarity: SemanticPolarity
    certainty: SemanticCertainty
    rule: SpeechTruthRule

    def __post_init__(self) -> None:
        for value, expected in (
            (self.fact_kind, SpeechSemanticFactKind),
            (self.claim_kind, SemanticClaimKind),
            (self.polarity, SemanticPolarity),
            (self.certainty, SemanticCertainty),
            (self.rule, SpeechTruthRule),
        ):
            if not isinstance(value, expected):
                raise ValueError("truth規則のfacet型が不正です")
        if self.execution_status is not None and not isinstance(
            self.execution_status, ExecutionStatus
        ):
            raise ValueError("truth規則の状態型が不正です")

    def matches(self, fact: SpeechSemanticFact) -> bool:
        return (
            fact.kind,
            fact.claim_kind,
            fact.execution_status,
            fact.polarity,
            fact.certainty,
        ) == (self.fact_kind, self.claim_kind, self.execution_status, self.polarity, self.certainty)


@dataclass(frozen=True, slots=True)
class SpeechTruthConstraintProjectionPolicy:
    policy_id: str
    revision: int
    rules: tuple[SpeechTruthConstraintProjectionRule, ...]

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.revision, "revision")
        if type(self.rules) is not tuple or any(
            not isinstance(x, SpeechTruthConstraintProjectionRule) for x in self.rules
        ):
            raise ValueError("truth規則が不正です")

    def project(self, fact: SpeechSemanticFact) -> SpeechTruthConstraint:
        matches = [x for x in self.rules if x.matches(fact)]
        if len(matches) != 1:
            raise SpeechSemanticContextError(C.TRUTH_RULE_UNRESOLVED)
        rule = matches[0].rule
        if (
            rule is SpeechTruthRule.PRESERVE_UNKNOWN
            and (
                fact.polarity is not SemanticPolarity.UNKNOWN
                or fact.certainty is not SemanticCertainty.UNKNOWN
            )
        ) or (
            rule is SpeechTruthRule.FORBID_COMPLETION_CLAIM
            and (
                fact.execution_status is None or fact.execution_status is ExecutionStatus.COMPLETED
            )
        ):
            raise SpeechSemanticContextError(C.TRUTH_RULE_UNRESOLVED)
        return SpeechTruthConstraint("truth:" + fact.fact_id, fact.fact_id, rule)


@dataclass(frozen=True, slots=True)
class SpeechSemanticFactProvenance:
    fact_id: str
    source_owner: str
    source_contract: str
    source_id: str
    source_revision: int
    projection_policy_id: str
    projection_policy_revision: int
    definition_ref: str | None = None
    meaning_policy_id: str | None = None
    meaning_policy_revision: int | None = None
    target_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "fact_id",
            "source_owner",
            "source_contract",
            "source_id",
            "projection_policy_id",
        ):
            require_identifier(getattr(self, name), name)
        require_revision(self.source_revision, "source_revision")
        require_revision(self.projection_policy_revision, "projection_policy_revision")
        if type(self.evidence_refs) is not tuple:
            raise ValueError("由来参照は不変tupleが必要です")

    def to_dict(self) -> dict[str, object]:
        from dataclasses import asdict

        return asdict(self)


@dataclass(frozen=True, slots=True)
class SpeechDeterministicDirectivePolicy:
    policy_id: str
    revision: int
    build: Callable[[SpeechSemanticContextSnapshot], DeterministicSpeechDirective | None]

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.revision, "revision")
        if not callable(self.build):
            raise ValueError("明示したdirective規則が必要です")


@dataclass(frozen=True, slots=True)
class SpeechSemanticContextGeneration:
    decision_id: str
    intent_id: str
    revisions: RevisionVector
    meaning_policy: SpeechSemanticMeaningPolicy
    projection_policy: SpeechSemanticFactProjectionPolicy
    truth_policy: SpeechTruthConstraintProjectionPolicy
    bounds: BrainOperationalBoundsPolicy
    sources: tuple[SpeechSemanticSourceBinding, ...]
    policy_tokens: tuple[AuthorityGenerationToken, ...]
    directive_policy: SpeechDeterministicDirectivePolicy | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "intent_id": self.intent_id,
            "meaning_policy_id": self.meaning_policy.policy_id,
            "meaning_policy_revision": self.meaning_policy.revision,
            "projection_policy_id": self.projection_policy.policy_id,
            "projection_policy_revision": self.projection_policy.revision,
            "truth_policy_id": self.truth_policy.policy_id,
            "truth_policy_revision": self.truth_policy.revision,
            "bounds_policy_id": self.bounds.policy_id,
            "bounds_policy_revision": self.bounds.policy_revision,
            "directive_policy": None
            if self.directive_policy is None
            else {
                "policy_id": self.directive_policy.policy_id,
                "revision": self.directive_policy.revision,
            },
            "sources": [x.resolution.to_dict() for x in self.sources],
        }

    def validate_snapshot(self, snapshot: SpeechSemanticContextSnapshot) -> None:
        if (
            snapshot.decision.decision_id,
            snapshot.intent_id,
            snapshot.revisions,
            snapshot.meaning_policy,
        ) != (self.decision_id, self.intent_id, self.revisions, self.meaning_policy):
            raise SpeechSemanticContextError(C.CONTEXT_STALE)
        entries = snapshot.fact_provenance
        if (
            type(entries) is not tuple
            or any(not isinstance(p, SpeechSemanticFactProvenance) for p in entries)
            or len(entries) != len(snapshot.facts)
            or {p.fact_id for p in entries} != {f.fact_id for f in snapshot.facts}
        ):
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
        for p in entries:
            if (p.projection_policy_id, p.projection_policy_revision) != (
                self.projection_policy.policy_id,
                self.projection_policy.revision,
            ):
                raise SpeechSemanticContextError(C.CONTEXT_STALE)
            if p.definition_ref is not None:
                definitions = self.meaning_policy.communicative_goal_catalog.definitions
                if (p.meaning_policy_id, p.meaning_policy_revision) != (
                    self.meaning_policy.policy_id,
                    self.meaning_policy.revision,
                ) or not any(
                    d.definition_id == p.definition_ref == p.fact_id
                    and d.definition_revision == p.source_revision
                    for d in definitions
                ):
                    raise SpeechSemanticContextError(C.CONTEXT_STALE)
            elif not any(
                b.resolution.selected_ref == p.fact_id
                and b.resolution.source is not None
                and (
                    b.resolution.source.source_owner,
                    b.resolution.source.source_contract_kind.value,
                    b.resolution.source.source_identity,
                    b.resolution.source.source_revision,
                )
                == (p.source_owner, p.source_contract, p.source_id, p.source_revision)
                for b in self.sources
            ):
                raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)

    @property
    def tokens(self) -> tuple[AuthorityGenerationToken, ...]:
        return self.policy_tokens + tuple(t for s in self.sources for t in s.tokens)

    def require_current(self) -> None:
        if not self.policy_tokens:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        for t in self.tokens:
            if t._participant.token() != t:
                raise SpeechSemanticContextError(C.CONTEXT_STALE)


@dataclass(frozen=True, slots=True)
class SpeechSemanticProductionPolicies:
    meaning: SpeechSemanticMeaningPolicy | None
    projection: SpeechSemanticFactProjectionPolicy
    truth: SpeechTruthConstraintProjectionPolicy
    bounds: BrainOperationalBoundsPolicy
    directive: SpeechDeterministicDirectivePolicy | None = None


class SpeechSemanticContextBuilder:
    def __init__(
        self,
        sources: SpeechSemanticContextSourcePort,
        current_policies: Callable[[], AuthorityReadPublication[SpeechSemanticProductionPolicies]],
    ) -> None:
        self._sources = sources
        self._current_policies = current_policies

    def build(
        self, decision: CommittedExecutiveDecision, intent_id: str, *, captured_at: datetime
    ) -> SpeechSemanticContextSnapshot:
        publication = self._current_policies()
        policies = publication.value
        meaning = require_meaning_policy(policies.meaning, policies.bounds)
        validate_resolution_keys(decision.candidate, decision.speech_reference_resolutions)
        selected = tuple(
            r for r in decision.speech_reference_resolutions if r.intent_id == intent_id
        )
        if not selected:
            raise SpeechSemanticContextError(C.SOURCE_NOT_FOUND)
        source_bindings = tuple(self._sources.resolve(r) for r in selected if r.source is not None)
        projector = SpeechSemanticFactProjector(policies.projection)
        explicit_constraints: list[SpeechTruthConstraint] = []
        facts: dict[str, SpeechSemanticFact] = {}
        provenance: dict[str, SpeechSemanticFactProvenance] = {}
        for binding in source_bindings:
            if isinstance(binding.value, SpeechSemanticConstraintSource):
                constraint = binding.value.constraint
                if (
                    binding.resolution.role is not ExecutiveSpeechReferenceRole.CONSTRAINT
                    or constraint.constraint_id != binding.resolution.selected_ref
                ):
                    raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
                explicit_constraints.append(constraint)
                continue
            fact = projector.project(binding)
            if fact.fact_id in facts and facts[fact.fact_id] != fact:
                raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
            facts[fact.fact_id] = fact
            if binding.resolution.role is ExecutiveSpeechReferenceRole.CONSTRAINT:
                rule = policies.truth.project(fact).rule
                explicit_constraints.append(
                    SpeechTruthConstraint(binding.resolution.selected_ref, fact.fact_id, rule)
                )
            source = binding.resolution.source
            assert source is not None
            provenance[fact.fact_id] = SpeechSemanticFactProvenance(
                fact.fact_id,
                source.source_owner,
                source.source_contract_kind.value,
                source.source_identity,
                source.source_revision,
                policies.projection.policy_id,
                policies.projection.revision,
            )
        for resolution in selected:
            if (
                resolution.resolution_kind
                is not ExecutiveSpeechResolutionKind.COMMUNICATIVE_ACT_DEFINITION
            ):
                continue
            if (resolution.meaning_policy_id, resolution.meaning_policy_revision) != (
                meaning.policy_id,
                meaning.revision,
            ):
                raise SpeechSemanticContextError(C.SEMANTIC_POLICY_STALE)
            definitions = [
                d
                for d in meaning.communicative_goal_catalog.definitions
                if d.definition_id == resolution.definition_id
                and d.definition_revision == resolution.definition_revision
            ]
            if len(definitions) != 1:
                raise SpeechSemanticContextError(C.SOURCE_REVISION_MISMATCH)
            definition = definitions[0]
            targets = [
                r.selected_ref for r in selected if r.role is ExecutiveSpeechReferenceRole.TARGET
            ]
            evidence = tuple(
                r.selected_ref for r in selected if r.role is ExecutiveSpeechReferenceRole.EVIDENCE
            )
            eligible = [
                s
                for s in source_bindings
                if s.resolution.role is ExecutiveSpeechReferenceRole.EVIDENCE
                and s.resolution.source is not None
                and s.resolution.source.source_contract_kind
                in definition.evidence_requirement.source_contracts
            ]
            if len(eligible) < definition.evidence_requirement.minimum_count or (
                definition.target_requirement.mode is CommunicativeTargetMode.REQUIRED
                and len(targets) != 1
            ):
                raise SpeechSemanticContextError(C.SOURCE_NOT_FOUND)
            for target in (
                b
                for b in source_bindings
                if b.resolution.role is ExecutiveSpeechReferenceRole.TARGET
            ):
                assert target.resolution.source is not None
                if (
                    target.resolution.source.source_contract_kind
                    not in definition.target_requirement.source_contracts
                ):
                    raise SpeechSemanticContextError(C.SOURCE_KIND_MISMATCH)
            shape = definition.semantic_shape
            subject = shape.subject_ref
            if shape.subject_binding is CommunicativeSubjectBinding.TARGET:
                if len(targets) != 1:
                    raise SpeechSemanticContextError(C.SOURCE_NOT_FOUND)
                subject = targets[0]
            elif shape.subject_binding is CommunicativeSubjectBinding.EVIDENCE:
                if shape.evidence_index is None or shape.evidence_index >= len(evidence):
                    raise SpeechSemanticContextError(C.SOURCE_NOT_FOUND)
                subject = evidence[shape.evidence_index]
            fact = SpeechSemanticFact(
                resolution.selected_ref,
                SpeechSemanticFactKind.DISCOURSE,
                subject,
                shape.predicate,
                shape.value,
                claim_kind=shape.claim_kind,
                polarity=shape.polarity,
                certainty=shape.certainty,
                degree=shape.degree,
                evidence_refs=evidence,
            )
            facts[fact.fact_id] = fact
            provenance[fact.fact_id] = SpeechSemanticFactProvenance(
                fact.fact_id,
                "SpeechSemantics",
                "communicative_definition",
                definition.definition_id,
                definition.definition_revision,
                policies.projection.policy_id,
                policies.projection.revision,
                definition.definition_id,
                meaning.policy_id,
                meaning.revision,
                targets[0] if targets else None,
                evidence,
            )
        constrained = {x.fact_ref for x in explicit_constraints}
        if not constrained <= set(facts):
            raise SpeechSemanticContextError(C.SOURCE_NOT_FOUND)
        for constraint in explicit_constraints:
            if policies.truth.project(facts[constraint.fact_ref]).rule is not constraint.rule:
                raise SpeechSemanticContextError(C.TRUTH_RULE_UNRESOLVED)
        constraints = tuple(explicit_constraints) + tuple(
            policies.truth.project(f) for f in facts.values() if f.fact_id not in constrained
        )
        candidate = decision.candidate
        revisions = RevisionVector(
            candidate.source_context_revision, candidate.goal_revision, candidate.attention_revision
        )
        generation = SpeechSemanticContextGeneration(
            decision.decision_id,
            intent_id,
            revisions,
            meaning,
            policies.projection,
            policies.truth,
            policies.bounds,
            source_bindings,
            publication.tokens,
            policies.directive,
        )
        generation.require_current()
        snapshot = SpeechSemanticContextSnapshot(
            decision,
            intent_id,
            tuple(facts.values()),
            constraints,
            (),
            meaning.self_disclosure_policy,
            meaning.max_question_budget,
            meaning.max_new_direction_budget,
            captured_at,
            meaning_policy=meaning,
            fact_provenance=tuple(provenance.values()),
            generation=generation,
        )
        if policies.directive is not None:
            directive = policies.directive.build(snapshot)
            snapshot = replace(snapshot, deterministic_directive=directive)
        from .bounds import SpeechSemanticBoundsError, validate_speech_semantic_context_bounds

        try:
            validate_speech_semantic_context_bounds(snapshot, policies.bounds)
        except SpeechSemanticBoundsError as exc:
            raise SpeechSemanticContextError(C.CONTEXT_TOO_LARGE) from exc
        if self._current_policies() != publication:
            raise SpeechSemanticContextError(C.CONTEXT_STALE)
        generation.require_current()
        return snapshot


class SpeechSemanticPolicyOwner:
    """明示登録された意味・投影・容量方針の同一世代公開を所有する。"""

    def __init__(self, policies: SpeechSemanticProductionPolicies) -> None:
        self._policies = policies
        self._participant = AuthorityFinalizationParticipant(self, "SpeechSemanticPolicyOwner", 65)
        self._validate(policies)
        self._meaning_history: dict[str, SpeechSemanticMeaningPolicy] = {}
        self._definition_history: dict[str, object] = {}
        self._remember_meaning(policies)

    def _remember_meaning(self, policies: SpeechSemanticProductionPolicies) -> None:
        meaning = policies.meaning
        if meaning is None:
            return
        previous = self._meaning_history.get(meaning.policy_id)
        if previous is not None and (
            meaning.revision < previous.revision
            or (meaning.revision == previous.revision and meaning != previous)
        ):
            raise ValueError("削除後も同じ意味方針世代を改変できません")
        definitions = meaning.communicative_goal_catalog.definitions
        for definition in definitions:
            key = definition.definition_id
            old = self._definition_history.get(key)
            if old is not None:
                from app.domain.speech_semantics_vocabulary import CommunicativeActDefinition

                assert isinstance(old, CommunicativeActDefinition)
                if definition.definition_revision < old.definition_revision or (
                    definition.definition_revision == old.definition_revision and definition != old
                ):
                    raise ValueError("同じ発話行為定義世代を改変できません")
        if (
            len(set(self._meaning_history) | {meaning.policy_id})
            > policies.bounds.executive.max_fact_refs
            or len(set(self._definition_history) | {d.definition_id for d in definitions})
            > policies.bounds.executive.max_fact_refs
        ):
            raise SpeechSemanticContextError(C.CONTEXT_TOO_LARGE)
        self._meaning_history[meaning.policy_id] = meaning
        self._definition_history.update((d.definition_id, d) for d in definitions)

    @staticmethod
    def _validate(policies: SpeechSemanticProductionPolicies) -> None:
        if not isinstance(policies, SpeechSemanticProductionPolicies):
            raise ValueError("明示した方針群が必要です")
        if policies.meaning is not None:
            policies.meaning.validate_bounds(policies.bounds)
        if (policies.truth.policy_id, policies.truth.revision) != (
            policies.projection.policy_id,
            policies.projection.revision,
        ):
            raise ValueError("Factとtruthの投影世代が一致しません")

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        return self._participant

    def publication(self) -> AuthorityReadPublication[SpeechSemanticProductionPolicies]:
        with self._participant:
            return AuthorityReadPublication(self._policies, (self._participant.token(),))

    def catalog_view(self) -> CommunicativeGoalCatalogView | None:
        with self._participant:
            meaning = self._policies.meaning
            return (
                None
                if meaning is None
                else replace(
                    meaning.communicative_goal_catalog,
                    publication_tokens=(self._participant.token(),),
                )
            )

    @authority_mutation
    def update(self, policies: SpeechSemanticProductionPolicies) -> None:
        with self._participant:
            self._validate(policies)
            old = self._policies
            for previous, current in (
                (old.meaning, policies.meaning),
                (old.projection, policies.projection),
                (old.truth, policies.truth),
                (old.directive, policies.directive),
            ):
                if (
                    previous is not None
                    and current is not None
                    and previous.policy_id == current.policy_id
                ):
                    if current.revision < previous.revision or (
                        current.revision == previous.revision and current != previous
                    ):
                        raise ValueError("同じ方針世代の内容変更またはリビジョン退行は禁止です")
            if old.bounds.policy_id == policies.bounds.policy_id and (
                policies.bounds.policy_revision < old.bounds.policy_revision
                or (
                    policies.bounds.policy_revision == old.bounds.policy_revision
                    and policies.bounds != old.bounds
                )
            ):
                raise ValueError("同じ容量世代の変更は禁止です")
            self._remember_meaning(policies)
            self._policies = policies
