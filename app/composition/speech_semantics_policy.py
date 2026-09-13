"""#362のユーザー採用済みMeaningPolicy V1と既存Ownerへの注入境界。"""

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.executive.contracts import ExecutiveFactRef
from app.domain.executive.speech_references import ExecutiveSpeechSourceBinding
from app.domain.speech_semantics.production import (
    SpeechDeterministicDirectivePolicy,
    SpeechSemanticContextBuilder,
    SpeechSemanticContextSourcePort,
    SpeechSemanticFactProjectionPolicy,
    SpeechSemanticPolicyOwner,
    SpeechSemanticProductionPolicies,
    SpeechTruthConstraintProjectionPolicy,
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
_GRATITUDE_SOURCES = (
    SpeechSourceContractKind.GOAL,
    SpeechSourceContractKind.COMMITMENT,
    SpeechSourceContractKind.EXECUTION,
    SpeechSourceContractKind.MEMORY,
    SpeechSourceContractKind.ATTENTION,
)
_DEFINITIONS = (
    ("yura.communicative.greeting", CommunicativeActKind.GREETING, (), 0),
    ("yura.communicative.acknowledgement", CommunicativeActKind.ACKNOWLEDGEMENT, (), 0),
    ("yura.communicative.gratitude", CommunicativeActKind.GRATITUDE, _GRATITUDE_SOURCES, 1),
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
        SelfDisclosurePolicy.FORBIDDEN,
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
    projection: SpeechSemanticFactProjectionPolicy,
    truth: SpeechTruthConstraintProjectionPolicy,
    bounds_policy: BrainOperationalBoundsPolicy,
    directive: SpeechDeterministicDirectivePolicy | None = None,
) -> SpeechSemanticPolicyOwner:
    """MeaningPolicyはV1 factoryから供給し、投影規則は明示登録を要求する。"""
    return SpeechSemanticPolicyOwner(
        SpeechSemanticProductionPolicies(
            build_speech_semantics_meaning_policy_v1(bounds_policy=bounds_policy),
            projection,
            truth,
            bounds_policy,
            directive,
        )
    )


SpeechSourceBindingReader = Callable[
    [tuple[ExecutiveFactRef, ...]], tuple[ExecutiveSpeechSourceBinding, ...]
]


@dataclass(frozen=True, slots=True)
class ExecutiveSpeechPolicyEvidence:
    """元Fact bindingと、同じ意味Ownerのread-only catalogを合流する。"""

    owner: SpeechSemanticPolicyOwner
    read_source_bindings: SpeechSourceBindingReader

    def capture_speech_sources(
        self,
        facts: tuple[ExecutiveFactRef, ...],
    ) -> tuple[CommunicativeGoalCatalogView | None, tuple[ExecutiveSpeechSourceBinding, ...]]:
        bindings = self.read_source_bindings(facts)
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
    sources: SpeechSemanticContextSourcePort,
    read_source_bindings: SpeechSourceBindingReader,
) -> SpeechSemanticPolicyBinding:
    """V1の実値を照合し、BuilderとExecutiveを同じOwnerへ接続する。"""
    policies = owner.publication().value
    meaning = require_meaning_policy(policies.meaning, policies.bounds)
    if meaning != build_speech_semantics_meaning_policy_v1(bounds_policy=policies.bounds):
        raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.SEMANTIC_POLICY_STALE)
    return SpeechSemanticPolicyBinding(
        owner,
        SpeechSemanticContextBuilder(sources, owner.publication),
        ExecutiveSpeechPolicyEvidence(owner, read_source_bindings),
    )
