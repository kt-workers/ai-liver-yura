"""採用済みOwner publicationをSpeech V1の参照と意味へ接続する。"""

from dataclasses import dataclass

from app.domain.activity_execution.authority import ActivityExecutionAuthority
from app.domain.activity_execution.contracts import ActivityExecutionRecord
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
from app.domain.memory.authority import MemoryStoreAuthority
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


@dataclass(frozen=True, slots=True)
class SpeechOwnerSourceRegistration:
    """参照IDと実Owner APIの明示的な対応。値を自己申告させない。"""

    fact_id: str
    fact_kind: ExecutiveFactKind
    source_identity: str
    source_contract: K


class ProductionSpeechSources(SpeechSemanticContextSourcePort):
    """開始/current/Builderで同じ実Ownerの公開を取得する。"""

    def __init__(
        self,
        *,
        goals: GoalCommitmentStore,
        memory: MemoryStoreAuthority,
        execution: ActivityExecutionAuthority,
        registrations: tuple[SpeechOwnerSourceRegistration, ...],
    ) -> None:
        super().__init__(())
        if (
            not isinstance(goals, GoalCommitmentStore)
            or not isinstance(memory, MemoryStoreAuthority)
            or not isinstance(execution, ActivityExecutionAuthority)
        ):
            raise ValueError("実Ownerの注入が必要です")
        self._goals, self._memory, self._execution = goals, memory, execution
        self._entries = {r.fact_id: r for r in registrations}
        if len(self._entries) != len(registrations):
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
        for r in registrations:
            if r.source_contract not in (K.GOAL, K.COMMITMENT, K.MEMORY, K.EXECUTION):
                raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
            # 既存typed DTOのkind対応検査を使い、payloadを参照しない。
            self._binding(r, 0, ())

    @staticmethod
    def _binding(
        r: SpeechOwnerSourceRegistration,
        revision: int,
        tokens: tuple[AuthorityGenerationToken, ...],
    ) -> ExecutiveSpeechSourceBinding:
        owner = {
            K.GOAL: "GoalCommitmentStore",
            K.COMMITMENT: "GoalCommitmentStore",
            K.MEMORY: "MemoryStoreAuthority",
            K.EXECUTION: "ActivityExecutionAuthority",
        }[r.source_contract]
        return ExecutiveSpeechSourceBinding(
            r.fact_id,
            ExecutiveSpeechResolutionKind.UPSTREAM_FACT,
            owner,
            r.source_contract,
            r.source_identity,
            revision,
            r.fact_id,
            r.fact_kind,
            revision,
            tokens,
        )

    def _read(
        self, r: SpeechOwnerSourceRegistration, revision: int
    ) -> AuthorityReadPublication[SourceValue]:
        publication: AuthorityReadPublication[SourceValue] | None
        if r.source_contract is K.GOAL:
            p = self._goals.goal_semantic_publication(r.source_identity)
            publication = None if p is None else AuthorityReadPublication(p.value, p.tokens)
        elif r.source_contract is K.COMMITMENT:
            p = self._goals.commitment_semantic_publication(r.source_identity)
            publication = None if p is None else AuthorityReadPublication(p.value, p.tokens)
        elif r.source_contract is K.MEMORY:
            m = self._memory.read_semantic_assertion_publication(r.source_identity, revision)
            publication = AuthorityReadPublication(m.value, m.tokens)
        else:
            e = self._execution.snapshot_publication(r.source_identity)
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
            identity, actual_revision = value.assertion.memory_id, value.assertion.memory_revision
        elif isinstance(value, GoalCommitmentSemanticView):
            expected = (
                GoalCommitmentSemanticModality.GOAL
                if r.source_contract is K.GOAL
                else GoalCommitmentSemanticModality.COMMITMENT
            )
            if value.modality is not expected:
                raise SpeechSemanticContextError(C.SOURCE_KIND_MISMATCH)
            identity, actual_revision = value.state_id, value.state_revision
        elif isinstance(value, ActivityExecutionRecord):
            identity, actual_revision = value.invocation.command.command_id, value.record_revision
        else:
            raise SpeechSemanticContextError(C.SOURCE_KIND_MISMATCH)
        if identity != r.source_identity:
            raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
        if actual_revision != revision:
            raise SpeechSemanticContextError(C.SOURCE_REVISION_MISMATCH)
        if not publication.tokens:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        expected_owner = self._binding(r, revision, publication.tokens).source_owner
        for t in publication.tokens:
            if t.owner_identity != expected_owner:
                raise SpeechSemanticContextError(C.SOURCE_OWNER_MISMATCH)
            if t._participant.token() != t:
                raise SpeechSemanticContextError(C.CONTEXT_STALE)
        return publication

    def capture(
        self, facts: tuple[ExecutiveFactRef, ...]
    ) -> tuple[ExecutiveSpeechSourceBinding, ...]:
        result = []
        seen: set[str] = set()
        for fact in facts:
            if fact.fact_id in seen:
                raise SpeechSemanticContextError(C.SOURCE_IDENTITY_MISMATCH)
            seen.add(fact.fact_id)
            r = self._entries.get(fact.fact_id)
            if r is None:
                continue
            if r.fact_kind is not fact.kind:
                raise SpeechSemanticContextError(C.SOURCE_KIND_MISMATCH)
            p = self._read(r, fact.revision)
            result.append(self._binding(r, fact.revision, p.tokens))
        return tuple(result)

    def resolve(
        self, resolution: ExecutiveSpeechReferenceResolution
    ) -> SpeechSemanticSourceBinding:
        r = self._entries.get(resolution.selected_ref)
        source = resolution.source
        if r is None or source is None:
            raise SpeechSemanticContextError(C.UNSUPPORTED_SOURCE_CONTRACT)
        publication = self._read(r, source.source_revision)
        expected = self._binding(r, source.source_revision, publication.tokens)
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
