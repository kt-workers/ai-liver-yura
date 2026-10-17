"""Executiveが判断に用いる根拠と、根拠読取のアプリケーション境界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.activity_binding import ActivityExecutionBindingPublication
from app.domain.attention import AttentionSource
from app.domain.contracts import CapabilityDescriptor, CapabilityRequirement
from app.domain.contracts.finalization import AuthorityGenerationToken
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveFactRef,
    ExecutivePreconditionRequirement,
    ExecutiveSourceEvent,
    PreconditionFact,
)
from app.domain.executive.speech_references import ExecutiveSpeechSourceBinding
from app.domain.input_meaning import StructuredInputMeaning
from app.domain.plan_execution.contracts import PlanExecutionScope
from app.domain.plan_execution.progress_contracts import PlanProgressContext
from app.domain.speech_semantics_vocabulary import CommunicativeGoalCatalogView


@dataclass(frozen=True, slots=True)
class CoreExecutiveEvidence:
    source: AttentionSource
    source_events: tuple[ExecutiveSourceEvent, ...]
    meaning: StructuredInputMeaning | None
    facts: tuple[ExecutiveFactRef, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    preconditions: tuple[PreconditionFact, ...]
    required_fact_ids: tuple[str, ...] = ()
    required_capabilities: tuple[CapabilityRequirement, ...] = ()
    required_preconditions: tuple[ExecutivePreconditionRequirement, ...] = ()
    plan_scopes: tuple[PlanExecutionScope, ...] = ()
    plan_progress_contexts: tuple[PlanProgressContext, ...] = ()
    activity_bindings: tuple[ActivityExecutionBindingPublication, ...] = ()
    communicative_goal_catalog: CommunicativeGoalCatalogView | None = None
    speech_source_bindings: tuple[ExecutiveSpeechSourceBinding, ...] = ()
    capability_tokens: tuple[AuthorityGenerationToken, ...] = ()
    precondition_tokens: tuple[tuple[str, tuple[AuthorityGenerationToken, ...]], ...] = ()
    memory_tokens: tuple[AuthorityGenerationToken, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, AttentionSource):
            raise ValueError("判断根拠には型付きの選択元が必要です")
        for name in (
            "source_events",
            "facts",
            "capabilities",
            "preconditions",
            "required_fact_ids",
            "required_capabilities",
            "required_preconditions",
            "plan_scopes",
            "plan_progress_contexts",
            "capability_tokens",
            "memory_tokens",
            "activity_bindings",
            "speech_source_bindings",
            "precondition_tokens",
        ):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)):
                raise ValueError("判断根拠の参照群は配列が必要です")
            object.__setattr__(self, name, tuple(value))


class CoreExecutiveEvidenceReader(Protocol):
    """意味・事実の所有者と、候補から独立した必須要件の読取境界。"""

    async def read(self, source: AttentionSource) -> CoreExecutiveEvidence: ...

    async def requirements_for(
        self,
        snapshot: ExecutiveContextSnapshot,
        candidate: ExecutiveDecisionCandidate,
    ) -> tuple[AuthoritativeIntentRequirements, ...]: ...
