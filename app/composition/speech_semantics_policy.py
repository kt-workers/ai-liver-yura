"""#362のユーザー採用済みMeaningPolicy V1と既存Ownerへの注入境界。"""

from dataclasses import dataclass

from app.composition.speech_semantics_sources import (
    ProductionSpeechSources,
    build_projection_v1,
    build_truth_v1,
)
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity
from app.domain.executive.contracts import ExecutiveFactRef
from app.domain.executive.speech_references import ExecutiveSpeechSourceBinding
from app.domain.speech_semantics.production import (
    SpeechDeterministicDirectivePolicy,
    SpeechSemanticContextBuilder,
    SpeechSemanticPolicyOwner,
    SpeechSemanticProductionPolicies,
)
from app.domain.speech_semantics_vocabulary import (
    CommunicativeActDefinition,
    CommunicativeActKind,
    CommunicativeEvidenceRequirement,
    CommunicativeGoalCatalogView,
    CommunicativeSemanticShape,
    CommunicativeSubjectBinding,
    CommunicativeTargetMode,
    CommunicativeTargetRequirement,
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticClaimKind,
    SemanticPolarity,
    SpeechSemanticContextError,
    SpeechSemanticContextFailureCode,
    SpeechSemanticMeaningPolicy,
    SpeechSourceContractKind,
    require_meaning_policy,
)

_MEANING_ID = "yura.speech-semantics.meaning"
_DEFINITIONS = (
    ("yura.communicative.greeting", CommunicativeActKind.GREETING, (), 0),
    ("yura.communicative.acknowledgement", CommunicativeActKind.ACKNOWLEDGEMENT, (), 0),
    ("yura.communicative.gratitude", CommunicativeActKind.GRATITUDE, (), 0),
    ("yura.communicative.apology", CommunicativeActKind.APOLOGY, (), 0),
    ("yura.communicative.request", CommunicativeActKind.REQUEST, (), 0),
    (
        "yura.communicative.commitment",
        CommunicativeActKind.COMMITMENT,
        (SpeechSourceContractKind.COMMITMENT,),
        1,
    ),
    ("yura.communicative.consent", CommunicativeActKind.CONSENT, (), 0),
    ("yura.communicative.refusal", CommunicativeActKind.REFUSAL, (), 0),
    ("yura.communicative.farewell", CommunicativeActKind.FAREWELL, (), 0),
)


def build_speech_semantics_meaning_policy_v1(
    *,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> SpeechSemanticMeaningPolicy:
    """明示呼出しで採用済み製品値を構築する。budgetは使用義務ではなく上限。"""
    if {row[1] for row in _DEFINITIONS} != set(CommunicativeActKind):
        raise ValueError("発話行為の型集合がV1採用定義と一致しません")
    definitions = tuple(
        CommunicativeActDefinition(
            definition_id,
            1,
            kind,
            CommunicativeSemanticShape(
                "current-interaction",
                "communicative-act",
                {"kind": kind.value},
                SemanticPolarity.AFFIRM,
                SemanticCertainty.CERTAIN,
                None,
                SemanticClaimKind.GENERAL,
                CommunicativeSubjectBinding.LITERAL,
                None,
            ),
            CommunicativeTargetRequirement(CommunicativeTargetMode.NONE, ()),
            CommunicativeEvidenceRequirement(contracts, minimum_count),
        )
        for definition_id, kind, contracts, minimum_count in _DEFINITIONS
    )
    meaning = SpeechSemanticMeaningPolicy(
        _MEANING_ID,
        1,
        SelfDisclosurePolicy.FACT_GROUNDED,
        1,
        1,
        CommunicativeGoalCatalogView(
            _MEANING_ID,
            1,
            definitions,
            bounds_policy.policy_id,
            bounds_policy.policy_revision,
        ),
    )
    meaning.validate_bounds(bounds_policy)
    return meaning


def build_speech_semantics_policy_owner_v1(
    *,
    runtime_subject_identity: RuntimeSubjectIdentity,
    bounds_policy: BrainOperationalBoundsPolicy,
    directive: SpeechDeterministicDirectivePolicy | None = None,
) -> SpeechSemanticPolicyOwner:
    """MeaningPolicyはV1 factoryから供給し、投影規則は明示登録を要求する。"""
    return SpeechSemanticPolicyOwner(
        SpeechSemanticProductionPolicies(
            build_speech_semantics_meaning_policy_v1(bounds_policy=bounds_policy),
            build_projection_v1(runtime_subject_identity),
            build_truth_v1(),
            bounds_policy,
            directive,
        )
    )


@dataclass(frozen=True, slots=True)
class ExecutiveSpeechPolicyEvidence:
    """元Fact bindingと、同じ意味Ownerのread-only catalogを合流する。"""

    owner: SpeechSemanticPolicyOwner
    sources: ProductionSpeechSources

    async def capture_speech_sources(
        self,
        facts: tuple[ExecutiveFactRef, ...],
    ) -> tuple[CommunicativeGoalCatalogView | None, tuple[ExecutiveSpeechSourceBinding, ...]]:
        policies = self.owner.publication()
        if len(facts) > policies.value.bounds.executive.max_fact_refs:
            raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.CONTEXT_TOO_LARGE)
        bindings = await self.sources.capture(facts)
        if self.owner.publication() != policies:
            raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.CONTEXT_STALE)
        return self.owner.catalog_view(), bindings


@dataclass(frozen=True, slots=True)
class SpeechSemanticPolicyBinding:
    """既存Ownerの公開先を束ねる。値や世代のAuthorityは追加しない。"""

    owner: SpeechSemanticPolicyOwner
    context_builder: SpeechSemanticContextBuilder
    executive_evidence: ExecutiveSpeechPolicyEvidence


def bind_speech_semantics_policy_v1(
    owner: SpeechSemanticPolicyOwner,
    *,
    sources: ProductionSpeechSources,
) -> SpeechSemanticPolicyBinding:
    """V1の実値を照合し、BuilderとExecutiveを同じOwnerへ接続する。"""
    if type(sources) is not ProductionSpeechSources:
        raise SpeechSemanticContextError(
            SpeechSemanticContextFailureCode.UNSUPPORTED_SOURCE_CONTRACT
        )
    policies = owner.publication().value
    meaning = require_meaning_policy(policies.meaning, policies.bounds)
    if meaning != build_speech_semantics_meaning_policy_v1(bounds_policy=policies.bounds):
        raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.SEMANTIC_POLICY_STALE)
    identity = policies.projection.runtime_subject_identity
    if (
        identity is None
        or policies.projection != build_projection_v1(identity)
        or policies.truth != build_truth_v1()
    ):
        raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.PROJECTION_POLICY_STALE)
    return SpeechSemanticPolicyBinding(
        owner,
        SpeechSemanticContextBuilder(sources, owner.publication),
        ExecutiveSpeechPolicyEvidence(owner, sources),
    )
