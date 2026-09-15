"""採用済みOwner publicationをSpeech V1の参照と意味へ接続する。"""

from dataclasses import dataclass
from types import MappingProxyType

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.domain.activity_execution.authority import ActivityExecutionAuthority
from app.domain.activity_execution.contracts import ActivityExecutionRecord
from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.contracts import ExecutionStatus
from app.domain.contracts.common import JsonValue
from app.domain.contracts.finalization import AuthorityGenerationToken, AuthorityReadPublication
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity, SemanticSubjectKind
from app.domain.executive.contracts import ExecutiveFactRef
from app.domain.executive.speech_references import (
    ExecutiveFactKind,
    ExecutiveSpeechReferenceResolution,
    ExecutiveSpeechResolutionKind,
    ExecutiveSpeechSourceBinding,
)
from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticModality,
    GoalCommitmentSemanticSubjectKind,
)
from app.domain.goals.semantic_views import GoalCommitmentSemanticView
from app.domain.goals.store import GoalCommitmentStore
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from app.domain.memory.semantic_assertions import MemorySemanticAssertionUnavailableReason as R
from app.domain.speech_semantics.contracts import SpeechSemanticFact
from app.domain.speech_semantics.production import (
    SourceValue,
    SpeechSemanticContextSourcePort,
    SpeechSemanticFactProjectionPolicy,
    SpeechSemanticFactProjectionRule,
    SpeechSemanticSourceBinding,
    SpeechTruthConstraintProjectionPolicy,
    SpeechTruthConstraintProjectionRule,
)
from app.domain.speech_semantics_vocabulary import (
    SemanticCertainty as S,
)
from app.domain.speech_semantics_vocabulary import (
    SemanticClaimKind as Q,
)
from app.domain.speech_semantics_vocabulary import (
    SemanticPolarity as P,
)
from app.domain.speech_semantics_vocabulary import (
    SpeechSemanticContextError,
)
from app.domain.speech_semantics_vocabulary import (
    SpeechSemanticContextFailureCode as C,
)
from app.domain.speech_semantics_vocabulary import (
    SpeechSemanticFactKind as F,
)
from app.domain.speech_semantics_vocabulary import (
    SpeechSourceContractKind as K,
)
from app.domain.speech_semantics_vocabulary import (
    SpeechTruthRule as T,
)
from app.infrastructure.persistence import PersistenceError


@dataclass(frozen=True, slots=True)
class SpeechOwnerSourceRegistration:
    """application lifetimeの型付きroute。具体的IDや値を登録しない。"""

    fact_kind: ExecutiveFactKind
    source_contract: K


_CONTRACTS = {
    ExecutiveFactKind.GOAL: K.GOAL,
    ExecutiveFactKind.COMMITMENT: K.COMMITMENT,
    ExecutiveFactKind.ACTIVITY: K.EXECUTION,
    ExecutiveFactKind.EXECUTION: K.EXECUTION,
    ExecutiveFactKind.MEMORY_EVIDENCE: K.MEMORY,
}
_OWNERS = {
    K.GOAL: "GoalCommitmentStore",
    K.COMMITMENT: "GoalCommitmentStore",
    K.MEMORY: "MemoryStoreAuthority",
    K.EXECUTION: "ActivityExecutionAuthority",
}
V1_SPEECH_SOURCE_ROUTES = tuple(
    SpeechOwnerSourceRegistration(kind, contract) for kind, contract in _CONTRACTS.items()
)


class ProductionSpeechSources(SpeechSemanticContextSourcePort):
    """boundedなFact選択からだけ実Ownerを取得し、IDのregistryを持たない。"""

    def __init__(
        self,
        *,
        goals: GoalCommitmentStore,
        memory: CoreMemoryPersistenceBinding,
        execution: ActivityExecutionAuthority,
        registrations: tuple[SpeechOwnerSourceRegistration, ...] = V1_SPEECH_SOURCE_ROUTES,
        bounds: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    ) -> None:
        super().__init__(())
        if (
            not isinstance(goals, GoalCommitmentStore)
            or not isinstance(memory, CoreMemoryPersistenceBinding)
            or not isinstance(execution, ActivityExecutionAuthority)
        ):
            raise ValueError("実OwnerとMemoryのpublic非同期境界の注入が必要です")
        self._goals, self._memory, self._execution = goals, memory, execution
        routes: dict[ExecutiveFactKind, K] = {}
        for r in registrations:
            if _CONTRACTS.get(r.fact_kind) is not r.source_contract:
                raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
            if r.fact_kind in routes:
                raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
            routes[r.fact_kind] = r.source_contract
        self._routes = MappingProxyType(routes)
        self._bounds = bounds

    @staticmethod
    def _binding(
        fact: ExecutiveFactRef,
        contract: K,
        tokens: tuple[AuthorityGenerationToken, ...],
    ) -> ExecutiveSpeechSourceBinding:
        return ExecutiveSpeechSourceBinding(
            fact.fact_id,
            ExecutiveSpeechResolutionKind.UPSTREAM_FACT,
            _OWNERS[contract],
            contract,
            fact.fact_id,
            fact.revision,
            fact.fact_id,
            fact.kind,
            fact.revision,
            tokens,
        )

    async def _read(
        self, contract: K, identity: str, revision: int
    ) -> AuthorityReadPublication[SourceValue]:
        publication: AuthorityReadPublication[SourceValue] | None
        if contract is K.GOAL:
            p = self._goals.goal_semantic_publication(identity)
            publication = None if p is None else AuthorityReadPublication(p.value, p.tokens)
        elif contract is K.COMMITMENT:
            p = self._goals.commitment_semantic_publication(identity)
            publication = None if p is None else AuthorityReadPublication(p.value, p.tokens)
        elif contract is K.MEMORY:
            try:
                result = await self._memory.read_semantic_assertion_publication(identity, revision)
            except PersistenceError as exc:
                raise SpeechSemanticContextError(C.SOURCE_UNAVAILABLE) from exc
            if result.failure_code is not None:
                raise SpeechSemanticContextError(C.SOURCE_UNAVAILABLE)
            m = result.value
            if m is None:
                raise SpeechSemanticContextError(C.SOURCE_UNAVAILABLE)
            publication = AuthorityReadPublication(m.value, m.tokens)
        else:
            e = self._execution.snapshot_publication(identity)
            publication = None if e.value is None else AuthorityReadPublication(e.value, e.tokens)
        if publication is None:
            raise SpeechSemanticContextError(C.SOURCE_NOT_FOUND)
        value = publication.value
        if isinstance(value, MemorySemanticAssertionEntry):
            if value.unavailable_reason is not None:
                code = {
                    R.SOURCE_NOT_FOUND: C.SOURCE_NOT_FOUND,
                    R.REVISION_STALE: C.SOURCE_REVISION_MISMATCH,
                    R.FINALIZATION_UNSUPPORTED: C.UNSUPPORTED_SOURCE_CONTRACT,
                    R.REPOSITORY_UNAVAILABLE: C.SOURCE_UNAVAILABLE,
                }.get(value.unavailable_reason, C.UNSUPPORTED_PROJECTION)
                raise SpeechSemanticContextError(code)
            if value.assertion is None:
                raise SpeechSemanticContextError(C.UNSUPPORTED_PROJECTION)
            actual_identity, actual_revision = (
                value.assertion.memory_id,
                value.assertion.memory_revision,
            )
        elif isinstance(value, GoalCommitmentSemanticView):
            expected = (
                GoalCommitmentSemanticModality.GOAL
                if contract is K.GOAL
                else GoalCommitmentSemanticModality.COMMITMENT
            )
            if value.modality is not expected:
                raise SpeechSemanticContextError(C.SOURCE_KIND_MISMATCH)
            actual_identity, actual_revision = value.state_id, value.state_revision
        elif isinstance(value, ActivityExecutionRecord):
            actual_identity, actual_revision = (
                value.invocation.command.command_id,
                value.record_revision,
            )
        else:
            raise SpeechSemanticContextError(C.SOURCE_KIND_MISMATCH)
        if actual_identity != identity:
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
        if actual_revision != revision:
            raise SpeechSemanticContextError(C.SOURCE_REVISION_MISMATCH)
        if not publication.tokens:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        expected_owner = _OWNERS[contract]
        for t in publication.tokens:
            if t.owner_identity != expected_owner:
                raise SpeechSemanticContextError(C.SOURCE_OWNER_MISMATCH)
            if t._participant.token() != t:
                raise SpeechSemanticContextError(C.CONTEXT_STALE)
        return publication

    async def capture(
        self, facts: tuple[ExecutiveFactRef, ...]
    ) -> tuple[ExecutiveSpeechSourceBinding, ...]:
        if len(facts) > self._bounds.executive.max_fact_refs:
            raise SpeechSemanticContextError(C.CONTEXT_TOO_LARGE)
        result = []
        seen: set[str] = set()
        for fact in facts:
            if fact.fact_id in seen:
                raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
            seen.add(fact.fact_id)
            contract = self._routes.get(fact.kind)
            if contract is None:
                continue
            p = await self._read(contract, fact.fact_id, fact.revision)
            result.append(self._binding(fact, contract, p.tokens))
        # 後続Memoryのawait中に先行Ownerが変わった場合も拒否する。
        for binding in result:
            for token in binding.source_tokens:
                if token._participant.token() != token:
                    raise SpeechSemanticContextError(C.CONTEXT_STALE)
        return tuple(result)

    async def acquire(
        self, resolution: ExecutiveSpeechReferenceResolution
    ) -> SpeechSemanticSourceBinding:
        source = resolution.source
        if source is None or source.fact_kind is None:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        contract = self._routes.get(source.fact_kind)
        if contract is None or source.source_contract_kind is not contract:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        if source.source_owner != _OWNERS[contract]:
            raise SpeechSemanticContextError(C.SOURCE_OWNER_MISMATCH)
        if source.source_identity != resolution.selected_ref:
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
        publication = await self._read(contract, source.source_identity, source.source_revision)
        fact = ExecutiveFactRef(
            resolution.selected_ref, source.fact_kind, source.source_revision, {}
        )
        expected = self._binding(fact, contract, publication.tokens)
        if source != expected:
            raise SpeechSemanticContextError(C.CONTEXT_STALE)
        return SpeechSemanticSourceBinding(resolution, publication.value, publication.tokens)


@dataclass(frozen=True, slots=True)
class _V1Projection:
    identity: RuntimeSubjectIdentity

    def __call__(
        self, value: SourceValue, resolution: ExecutiveSpeechReferenceResolution
    ) -> SpeechSemanticFact:
        if isinstance(value, ActivityExecutionRecord):
            return SpeechSemanticFact(
                resolution.selected_ref,
                F.EXECUTION,
                value.invocation.command.command_id,
                "execution-status",
                value.result.status.value,
                claim_kind=Q.EXECUTION_STATUS,
                execution_status=value.result.status,
                polarity=P.AFFIRM,
                certainty=S.CERTAIN,
            )
        try:
            if isinstance(value, GoalCommitmentSemanticView):
                spec = value.semantic_spec
                if spec.subject_kind is GoalCommitmentSemanticSubjectKind.SELF:
                    subject = self.identity.self_subject()
                else:
                    assert spec.subject_ref is not None
                    subject = self.identity.reference_subject(spec.subject_ref)
                predicate = "goal-commitment-state"
                envelope: JsonValue = {
                    "modality": value.modality.value,
                    "lifecycle_status": value.lifecycle_status.value,
                    "semantic_predicate": spec.predicate,
                    "semantic_value": spec.value,
                    "semantic_polarity": spec.polarity.value,
                    "semantic_degree": spec.degree,
                }
                polarity, certainty = P.AFFIRM, S(value.certainty.value)
            elif isinstance(value, MemorySemanticAssertionEntry) and value.assertion is not None:
                assertion = value.assertion
                subject = assertion.subject_identity
                self.identity.validate(subject)
                predicate = assertion.predicate
                envelope = {
                    "semantic_value": assertion.value,
                    "temporal_meaning": assertion.temporal_meaning.value,
                    "temporal_scope_ref": assertion.temporal_scope_ref,
                    "qualifiers": assertion.qualifiers,
                }
                polarity, certainty = P(assertion.polarity.value), S(assertion.certainty.value)
            else:
                raise SpeechSemanticContextError(C.UNSUPPORTED_PROJECTION)
        except ValueError as exc:
            if isinstance(exc, SpeechSemanticContextError):
                raise
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH) from exc
        return SpeechSemanticFact(
            resolution.selected_ref,
            F.SELF if subject.kind is SemanticSubjectKind.SELF else F.GENERAL,
            subject.subject_ref,
            predicate,
            envelope,
            polarity=polarity,
            certainty=certainty,
        )


@dataclass(frozen=True, slots=True)
class _V1SourceMatch:
    contract: K

    def __call__(self, value: SourceValue) -> bool:
        if self.contract in (K.GOAL, K.COMMITMENT):
            return isinstance(value, GoalCommitmentSemanticView) and value.modality is (
                GoalCommitmentSemanticModality.GOAL
                if self.contract is K.GOAL
                else GoalCommitmentSemanticModality.COMMITMENT
            )
        if self.contract is K.MEMORY:
            return isinstance(value, MemorySemanticAssertionEntry) and value.assertion is not None
        return self.contract is K.EXECUTION and isinstance(value, ActivityExecutionRecord)


def build_projection_v1(identity: RuntimeSubjectIdentity) -> SpeechSemanticFactProjectionPolicy:
    if not isinstance(identity, RuntimeSubjectIdentity):
        raise ValueError("RuntimeSubjectIdentityの明示注入が必要です")
    return SpeechSemanticFactProjectionPolicy(
        "yura.speech-semantics.projection",
        1,
        tuple(
            SpeechSemanticFactProjectionRule(k, _V1Projection(identity), _V1SourceMatch(k))
            for k in (K.GOAL, K.COMMITMENT, K.MEMORY, K.EXECUTION)
        ),
        identity,
    )


def build_truth_v1() -> SpeechTruthConstraintProjectionPolicy:
    rows = [
        SpeechTruthConstraintProjectionRule(
            kind, Q.GENERAL, None, polarity, certainty, T.REQUIRE_MATCH
        )
        for kind in (F.SELF, F.GENERAL)
        for polarity in (P.AFFIRM, P.NEGATE)
        for certainty in (S.CERTAIN, S.LIKELY, S.UNCERTAIN)
    ]
    rows.append(
        SpeechTruthConstraintProjectionRule(
            F.DISCOURSE, Q.GENERAL, None, P.AFFIRM, S.CERTAIN, T.REQUIRE_MATCH
        )
    )
    rows.extend(
        SpeechTruthConstraintProjectionRule(
            F.EXECUTION,
            Q.EXECUTION_STATUS,
            status,
            P.AFFIRM,
            S.CERTAIN,
            T.REQUIRE_MATCH if status is ExecutionStatus.COMPLETED else T.FORBID_COMPLETION_CLAIM,
        )
        for status in ExecutionStatus
    )
    return SpeechTruthConstraintProjectionPolicy("yura.speech-semantics.projection", 1, tuple(rows))
