"""注意の選択元と現在状態を、既存の実行判断と確定検査へ接続する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Protocol

from app.composition.attention import CoreAttentionBinding, CoreAttentionDispatch
from app.domain.activity_binding import ActivityExecutionBindingPublication
from app.domain.attention import AttentionSource, AttentionSourceKind
from app.domain.brain_integration import (
    BrainIntegrationModule,
    BrainIntegrationWork,
    BrainWorkEnvelope,
)
from app.domain.contracts import CapabilityDescriptor, CapabilityRequirement, RevisionVector
from app.domain.contracts.common import require_identifier
from app.domain.contracts.finalization import AuthorityGenerationToken
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    CommittedExecutiveDecision,
    ExecutiveBoundsProvenance,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionAuthority,
    ExecutiveDecisionCandidate,
    ExecutiveDeliberator,
    ExecutiveFactRef,
    ExecutiveFreshnessStamp,
    ExecutivePolicy,
    ExecutivePreconditionRequirement,
    ExecutiveSourceEvent,
    PreconditionFact,
    build_executive_context_snapshot,
)
from app.domain.input_meaning import StructuredInputMeaning
from app.domain.plan_execution.contracts import PlanExecutionScope
from app.domain.plan_execution.progress_contracts import PlanProgressContext
from app.runtime.kernel import CancellationToken, RuntimeClock
from app.usecases.ports.llm import LLMRolePort


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
    capability_tokens: tuple[AuthorityGenerationToken, ...] = ()
    precondition_tokens: tuple[tuple[str, tuple[AuthorityGenerationToken, ...]], ...] = ()

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
            "activity_bindings",
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


class CoreExecutiveBinding:
    def __init__(
        self,
        attention: CoreAttentionBinding,
        evidence: CoreExecutiveEvidenceReader,
        llm: LLMRolePort,
        policy: ExecutivePolicy,
        authority: ExecutiveDecisionAuthority,
        clock: RuntimeClock,
    ) -> None:
        if not isinstance(attention, CoreAttentionBinding):
            raise ValueError("実行判断には本体の注意接続が必要です")
        if not isinstance(authority, ExecutiveDecisionAuthority):
            raise ValueError("実行判断には既存の判断確定所有者が必要です")
        self._attention = attention
        self._evidence = evidence
        self._llm = llm
        self._policy = policy
        self._authority = authority
        self._clock = clock
        self._latest: CommittedExecutiveDecision | None = None

    def latest_decision(self) -> CommittedExecutiveDecision | None:
        """確定済み判断を保持し、現在も実行可能であるとは主張しない。"""
        return self._latest

    def is_current(self, dispatch: CoreAttentionDispatch) -> bool:
        """実行基盤の開始前検査にも同じ所有者の現在値を使う。"""
        return self._attention.is_current(dispatch)

    async def deliberate(
        self,
        dispatch: CoreAttentionDispatch,
        *,
        request_id: str,
        trace_id: str,
        decision_id: str,
        cancellation: CancellationToken,
        envelope: BrainWorkEnvelope | None = None,
    ) -> CommittedExecutiveDecision:
        if envelope is not None:
            _validate_envelope(dispatch, envelope)
            if envelope.trace_id != trace_id:
                raise ValueError("判断処理の追跡識別子が一致しません")
        operation = _ExecutiveOperation(self, dispatch, cancellation, envelope)
        task = asyncio.create_task(operation.run(request_id, trace_id, decision_id))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            operation.cancelled = True
            task.cancel()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
            raise


class _ExecutiveOperation:
    def __init__(
        self,
        binding: CoreExecutiveBinding,
        dispatch: CoreAttentionDispatch,
        cancellation: CancellationToken,
        envelope: BrainWorkEnvelope | None,
    ) -> None:
        self.envelope = envelope
        self.binding = binding
        self.dispatch = dispatch
        self.cancellation = cancellation
        self.cancelled = False
        self.evidence: CoreExecutiveEvidence | None = None

    def check_current(self) -> None:
        if self.cancelled or self.cancellation.cancelled:
            raise asyncio.CancelledError
        if not self.binding._attention.is_current(self.dispatch):
            raise ValueError("注意の搬送結果が現在の状態と一致しません")

    async def read(self) -> CoreExecutiveEvidence:
        self.check_current()
        value = await self.binding._evidence.read(self.dispatch.selected_source)
        self.check_current()
        if (
            not isinstance(value, CoreExecutiveEvidence)
            or value.source != self.dispatch.selected_source
        ):
            raise ValueError("判断根拠の供給元が注意の選択元と一致しません")
        selected = self.dispatch.selected_appraisal
        expected = (
            set(selected.candidate.source_event_ids)
            if selected is not None
            else {value.source.source_ref}
            if value.source.kind is AttentionSourceKind.USER_INTERACTION
            else None
        )
        if (
            expected is not None
            and {item.event_id for item in value.source_events if item.is_trigger_lineage}
            != expected
        ):
            raise ValueError("判断根拠の元イベントが注意の選択元と一致しません")
        if self.envelope is not None and set(self.envelope.source_event_ids) != {
            item.event_id for item in value.source_events if item.is_trigger_lineage
        }:
            raise ValueError("判断処理の元イベントが供給元の根拠と一致しません")
        return value

    async def run(
        self, request_id: str, trace_id: str, decision_id: str
    ) -> CommittedExecutiveDecision:
        evidence = await self.read()
        self.evidence = evidence
        dispatch, policy = self.dispatch, self.binding._policy
        current = dispatch.current_appraisal
        if current is None:
            raise ValueError("判断に必要な現在の評価事実がありません")
        snapshot = build_executive_context_snapshot(
            trigger_id=dispatch.trigger.trigger_id,
            source_events=evidence.source_events,
            source_context_revision=dispatch.reference.context.source_context_revision,
            goal_revision=dispatch.reference.goals.goal_revision,
            attention_revision=dispatch.trigger.attention_revision,
            meaning=evidence.meaning,
            internal_state=dispatch.current_state,
            facts=evidence.facts,
            required_fact_ids=evidence.required_fact_ids,
            capabilities=evidence.capabilities,
            required_capabilities=evidence.required_capabilities,
            preconditions=evidence.preconditions,
            required_preconditions=evidence.required_preconditions,
            captured_at=self.binding._clock.now(),
            appraisal_facts=current.appraisal_facts,
            bounds_policy=policy.bounds,
            activity_bindings=evidence.activity_bindings,
            plan_scopes=evidence.plan_scopes,
            plan_progress_contexts=evidence.plan_progress_contexts,
        )
        owner = ExecutiveDeliberator(
            self.binding._llm,
            self,
            policy,
            self.binding._authority,
            clock=self.binding._clock,
        )
        result = await owner.deliberate(
            snapshot,
            request_id=request_id,
            trace_id=trace_id,
            decision_id=decision_id,
            created_at=self.binding._clock.now(),
        )
        self.binding._latest = result
        return result

    async def current_for_commit(
        self,
        snapshot: ExecutiveContextSnapshot,
        candidate: ExecutiveDecisionCandidate,
    ) -> ExecutiveCommitState:
        self.check_current()
        requirements = await self.binding._evidence.requirements_for(snapshot, candidate)
        current = await self.read()
        assert self.evidence is not None
        # 使用能力・前提条件の変化は既存の候補別検査へ渡す。その他の根拠は固定する。
        if (
            replace(
                current,
                capabilities=self.evidence.capabilities,
                preconditions=self.evidence.preconditions,
                capability_tokens=self.evidence.capability_tokens,
                precondition_tokens=self.evidence.precondition_tokens,
            )
            != self.evidence
        ):
            raise ValueError("判断中に選択元の意味・根拠・計画参照が変更されました")
        self.check_current()
        owners = self.binding._attention.read_current(self.dispatch)
        appraisal = owners.appraisal
        assert appraisal is not None
        used_conditions = {r.precondition_id for item in requirements for r in item.preconditions}
        evidence_tokens = (
            *(current.capability_tokens if any(item.capabilities for item in requirements) else ()),
            *(
                token
                for ref, tokens in current.precondition_tokens
                if ref in used_conditions
                for token in tokens
            ),
        )
        return ExecutiveCommitState(
            ExecutiveFreshnessStamp(
                RevisionVector(
                    owners.reference.context.source_context_revision,
                    owners.reference.goals.goal_revision,
                    owners.attention.revision,
                ),
                owners.internal_state.revision,
                appraisal.appraisal_facts.revision,
            ),
            current.capabilities,
            current.preconditions,
            requirements,
            ExecutiveBoundsProvenance.from_policy(self.binding._policy.bounds),
            current.plan_scopes,
            current.plan_progress_contexts,
            evidence_tokens=evidence_tokens,
            activity_bindings=current.activity_bindings,
        )


@dataclass(frozen=True, slots=True)
class ExecutiveBrainWorkPayload:
    dispatch: CoreAttentionDispatch
    request_id: str
    decision_id: str


def _validate_envelope(dispatch: CoreAttentionDispatch, envelope: BrainWorkEnvelope) -> None:
    if not isinstance(dispatch, CoreAttentionDispatch) or not isinstance(
        envelope, BrainWorkEnvelope
    ):
        raise ValueError("判断処理には型付きの注意搬送と相関情報が必要です")
    if (
        envelope.trigger_id != dispatch.trigger.trigger_id
        or envelope.source_context_revision != dispatch.reference.context.source_context_revision
        or envelope.goal_revision != dispatch.reference.goals.goal_revision
        or envelope.attention_revision != dispatch.trigger.attention_revision
    ):
        raise ValueError("判断処理の契機・文脈・目標・注意が搬送と一致しません")


class ExecutiveBrainModulePort:
    """既存本体実行の有界な受付と取消・停止へ判断を登録する。"""

    def __init__(self, binding: CoreExecutiveBinding) -> None:
        self._binding = binding

    @staticmethod
    def _validate(work: BrainIntegrationWork) -> ExecutiveBrainWorkPayload:
        payload = work.payload
        if work.module is not BrainIntegrationModule.EXECUTIVE or not isinstance(
            payload, ExecutiveBrainWorkPayload
        ):
            raise ValueError("判断処理の構成入力が不正です")
        require_identifier(payload.request_id, "request_id")
        require_identifier(payload.decision_id, "decision_id")
        _validate_envelope(payload.dispatch, work.envelope)
        return payload

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        payload = self._validate(work)
        return self._binding.is_current(payload.dispatch)

    async def execute(
        self, work: BrainIntegrationWork, cancellation: CancellationToken
    ) -> CommittedExecutiveDecision:
        payload = self._validate(work)
        return await self._binding.deliberate(
            payload.dispatch,
            request_id=payload.request_id,
            trace_id=work.envelope.trace_id,
            decision_id=payload.decision_id,
            cancellation=cancellation,
            envelope=work.envelope,
        )
