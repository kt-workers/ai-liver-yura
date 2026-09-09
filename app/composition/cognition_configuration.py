"""通常認知へ登録する方針と現在の所有者を、起動時に明示する。"""

from dataclasses import dataclass

from app.composition.accepted_input import CoreAcceptedInputStore
from app.composition.appraisal import CoreAppraisalBinding
from app.composition.attention import CoreAttentionBinding
from app.composition.cognition import CoreCognitionDelivery
from app.composition.executive import CoreExecutiveBinding
from app.composition.executive_requirements import (
    CoreExecutiveRequirementsReader,
    CorePreconditionSourceReader,
    build_core_executive_input_evidence,
)
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.domain.appraisal import (
    DeepAppraisalPolicy,
    DeterministicAppraisalRule,
    InternalStateReducer,
)
from app.domain.attention import AttentionTurnStore
from app.domain.brain_integration import BrainIntegrationRuntime
from app.domain.contracts.preconditions import PreconditionSourceBinding, PreconditionSourceRouter
from app.domain.executive import (
    ExecutiveDecisionAuthority,
    ExecutivePolicy,
    ExecutiveRequirementsOwner,
)
from app.domain.plugin_registry.authority import PluginRegistryAuthority
from app.runtime.kernel import RuntimeClock
from app.usecases.ports.llm import LLMRolePort


@dataclass(frozen=True, slots=True)
class CoreCognitionConfiguration:
    """意味Ownerが保持する現在値を使い、配送側で初期事実を生成しない。"""

    appraisal_policy: DeepAppraisalPolicy
    executive_policy: ExecutivePolicy
    state: InternalStateReducer
    attention: AttentionTurnStore
    requirements: ExecutiveRequirementsOwner
    registry: PluginRegistryAuthority
    precondition_router: PreconditionSourceRouter
    precondition_bindings: tuple[PreconditionSourceBinding, ...]
    fast_rules: tuple[DeterministicAppraisalRule, ...]

    def __post_init__(self) -> None:
        registrations = (
            (self.appraisal_policy, DeepAppraisalPolicy),
            (self.executive_policy, ExecutivePolicy),
            (self.state, InternalStateReducer),
            (self.attention, AttentionTurnStore),
            (self.requirements, ExecutiveRequirementsOwner),
            (self.registry, PluginRegistryAuthority),
            (self.precondition_router, PreconditionSourceRouter),
        )
        if any(not isinstance(value, expected) for value, expected in registrations):
            raise ValueError("通常認知の起動には既存Owner・方針・実測Routerの明示登録が必要です")
        object.__setattr__(self, "precondition_bindings", tuple(self.precondition_bindings))
        object.__setattr__(self, "fast_rules", tuple(self.fast_rules))
        # 未登録方針を、要件なしという方針へ置き換えない。
        self.requirements.current_generation()
        if len(self.fast_rules) > self.executive_policy.bounds.executive.max_fact_refs:
            raise ValueError("定型評価規則が構成上限を超えています")
        if any(not isinstance(rule, DeterministicAppraisalRule) for rule in self.fast_rules):
            raise ValueError("定型評価には既存の型付き規則が必要です")

    def compose(
        self,
        brain: BrainIntegrationRuntime,
        reference: CoreInputReferenceContextBinding,
        inputs: CoreAcceptedInputStore,
        llm: LLMRolePort,
        clock: RuntimeClock,
    ) -> CoreCognitionDelivery:
        """同じ所有者を評価・注意・候補検査・最終Fenceまで接続する。"""
        appraisal = CoreAppraisalBinding(reference, self.state, llm, self.appraisal_policy, clock)
        attention = CoreAttentionBinding(appraisal, self.attention, clock)
        preconditions = CorePreconditionSourceReader(
            self.precondition_router, self.precondition_bindings, self.executive_policy.bounds
        )
        requirements = CoreExecutiveRequirementsReader(
            self.requirements, preconditions, self.executive_policy.bounds
        )
        evidence = build_core_executive_input_evidence(
            inputs, appraisal, self.registry, requirements
        )
        executive = CoreExecutiveBinding(
            attention,
            evidence,
            llm,
            self.executive_policy,
            ExecutiveDecisionAuthority(self.requirements),
            clock,
        )
        return CoreCognitionDelivery(
            brain, appraisal, attention, executive, self.fast_rules, inputs, self.attention, clock
        )
