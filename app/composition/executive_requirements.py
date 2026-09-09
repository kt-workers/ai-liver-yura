"""既存所有者の必須要件と計画根拠を判断の読取境界へ供給する。"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from app.composition.accepted_input import CoreAcceptedInputStore
from app.composition.appraisal import CoreAppraisalBinding
from app.composition.executive_input_evidence import CoreExecutiveInputEvidenceReader
from app.domain.attention import AttentionSource, AttentionSourceKind
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts.common import freeze_json, require_identifier
from app.domain.contracts.finalization import AuthorityGenerationToken, AuthorityReadPublication
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveRequirementsOwner,
    PreconditionFact,
    RequirementsFailureCode,
    RequirementsRejected,
)
from app.domain.executive.requirements import RequirementSourcePublication, typed_json
from app.domain.plan_execution.contracts import PlanExecutionScope
from app.domain.plan_execution.owner import PlanExecutionOwner
from app.domain.plan_execution.progress_contracts import PlanProgressContext
from app.domain.plugin_registry.authority import PluginRegistryAuthority


class CoreExecutivePreconditionReader(Protocol):
    """必要条件の意味を変えず、正規所有者の現在の実測事実を読む。"""

    async def preconditions_for(
        self, source: AttentionSource
    ) -> tuple[AuthorityReadPublication[PreconditionFact], ...]: ...


@dataclass(frozen=True, slots=True)
class CoreExecutivePlanReferences:
    """構成側が選択元へ明示登録した範囲。接続側で計画を選ばない。"""

    scope_ids: tuple[str, ...] = ()
    progress_scope_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("scope_ids", "progress_scope_ids"):
            values = tuple(getattr(self, name))
            for value in values:
                require_identifier(value, name)
            if len(set(values)) != len(values):
                raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
            object.__setattr__(self, name, values)


class CoreExecutiveRequirementsReader:
    """要件の意味はExecutiveへ委譲し、現在の公開根拠だけを供給する。"""

    def __init__(
        self,
        owner: ExecutiveRequirementsOwner,
        preconditions: CoreExecutivePreconditionReader,
        bounds: BrainOperationalBoundsPolicy,
        *,
        plans: PlanExecutionOwner | None = None,
        references: Mapping[tuple[AttentionSourceKind, str], CoreExecutivePlanReferences]
        | None = None,
    ) -> None:
        if not isinstance(owner, ExecutiveRequirementsOwner):
            raise RequirementsRejected(RequirementsFailureCode.POLICY_UNREGISTERED)
        refs = dict(references or {})
        if len(refs) > bounds.executive.max_fact_refs:
            raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
        for (kind, source_ref), value in refs.items():
            if not isinstance(kind, AttentionSourceKind) or not isinstance(
                value, CoreExecutivePlanReferences
            ):
                raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
            require_identifier(source_ref, "source_ref")
            if (
                len(value.scope_ids) + len(value.progress_scope_ids)
                > bounds.executive.max_fact_refs
            ):
                raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
            if (value.scope_ids or value.progress_scope_ids) and plans is None:
                raise RequirementsRejected(RequirementsFailureCode.SCOPE_UNAVAILABLE)
        self.owner = owner
        self._preconditions = preconditions
        self._bounds = bounds.executive
        self._plans = plans
        self._references = MappingProxyType(refs)

    async def preconditions_for(
        self, source: AttentionSource
    ) -> tuple[AuthorityReadPublication[PreconditionFact], ...]:
        self.owner.current_generation()
        try:
            publications = tuple(await self._preconditions.preconditions_for(source))
        except RequirementsRejected:
            raise
        except Exception:
            raise RequirementsRejected(RequirementsFailureCode.SOURCE_UNAVAILABLE) from None
        if any(
            not isinstance(item, AuthorityReadPublication)
            or not isinstance(item.value, PreconditionFact)
            or not item.tokens
            or len(item.tokens) > self._bounds.max_fact_refs
            or any(not isinstance(token, AuthorityGenerationToken) for token in item.tokens)
            for item in publications
        ):
            raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
        values = tuple(item.value for item in publications)
        if (
            len(values) > self._bounds.max_precondition_facts
            or any(not isinstance(value, PreconditionFact) for value in values)
            or len({value.precondition_id for value in values}) != len(values)
        ):
            raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
        if any(
            len(
                json.dumps(
                    value.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
            > self._bounds.max_fact_payload_json_bytes
            for value in values
        ):
            raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
        return publications

    async def requirements_for(
        self,
        snapshot: ExecutiveContextSnapshot,
        candidate: ExecutiveDecisionCandidate,
    ) -> tuple[AuthoritativeIntentRequirements, ...]:
        result = self.owner.derive(snapshot, candidate)
        if result.failure is not None:
            raise RequirementsRejected(result.failure.code)
        return tuple(value.requirements for value in result.values)

    def plans_for(
        self,
        source: AttentionSource,
    ) -> tuple[tuple[PlanExecutionScope, ...], tuple[PlanProgressContext, ...]]:
        generation = self.owner.current_generation()
        references = self._references.get((source.kind, source.source_ref))
        if references is None or not (references.scope_ids or references.progress_scope_ids):
            return (), ()
        assert self._plans is not None
        try:
            scopes = tuple(self._plans.scope_publication(ref) for ref in references.scope_ids)
            contexts = tuple(
                self._plans.observation_publication(ref) for ref in references.progress_scope_ids
            )
        except Exception:
            raise RequirementsRejected(RequirementsFailureCode.SOURCE_UNAVAILABLE) from None
        publications: tuple[
            AuthorityReadPublication[PlanExecutionScope]
            | AuthorityReadPublication[PlanProgressContext],
            ...,
        ] = (*scopes, *contexts)
        for publication in publications:
            value = publication.value
            expected = tuple(
                item
                for item in generation.sources
                if type(item.value) is type(value) and self._same_plan_value(item, value)
            )
            if len(expected) != 1 or expected[0].tokens != publication.tokens:
                raise RequirementsRejected(RequirementsFailureCode.STALE_SOURCE)
        if self.owner.current_generation() is not generation:
            raise RequirementsRejected(RequirementsFailureCode.STALE_POLICY)
        return tuple(p.value for p in scopes), tuple(p.value for p in contexts)

    @staticmethod
    def _same_plan_value(
        publication: RequirementSourcePublication,
        value: PlanExecutionScope | PlanProgressContext,
    ) -> bool:
        current = publication.value
        return isinstance(current, (PlanExecutionScope, PlanProgressContext)) and (
            typed_json(freeze_json(current.to_dict())) == typed_json(freeze_json(value.to_dict()))
        )


def build_core_executive_input_evidence(
    inputs: CoreAcceptedInputStore,
    appraisal: CoreAppraisalBinding,
    registry: PluginRegistryAuthority,
    requirements: CoreExecutiveRequirementsReader,
) -> CoreExecutiveInputEvidenceReader:
    """同じ登録済み読取を入力根拠・現在要件・計画根拠へ接続する。"""
    return CoreExecutiveInputEvidenceReader(
        inputs, appraisal, registry, requirements, plans=requirements
    )
