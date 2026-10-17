"""Executive判断を実行し、確定前後の鮮度と根拠を検証する。"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from app.domain.attention import AttentionSourceKind
from app.domain.brain_integration import BrainWorkEnvelope
from app.domain.contracts import RevisionVector
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveBoundsProvenance,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionAuthority,
    ExecutiveDecisionCandidate,
    ExecutiveDeliberator,
    ExecutiveFreshnessStamp,
    ExecutivePolicy,
    build_executive_context_snapshot,
)
from app.runtime.kernel import CancellationToken, RuntimeClock
from app.usecases.attention_binding import CoreAttentionBinding, CoreAttentionDispatch
from app.usecases.executive_evidence import CoreExecutiveEvidence, CoreExecutiveEvidenceReader
from app.usecases.ports.llm import LLMRolePort


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

    async def read(
        self, candidate: ExecutiveDecisionCandidate | None = None
    ) -> CoreExecutiveEvidence:
        self.check_current()
        selected_reader = getattr(self.binding._evidence, "read_for_candidate", None)
        value = (
            await selected_reader(self.dispatch.selected_source, candidate)
            if candidate is not None and selected_reader is not None
            else await self.binding._evidence.read(self.dispatch.selected_source)
        )
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
            communicative_goal_catalog=evidence.communicative_goal_catalog,
            speech_source_bindings=evidence.speech_source_bindings,
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
        current = await self.read(candidate)
        assert self.evidence is not None
        # Memory tokenは同期証拠であり、読取ごとのidentityを根拠値と比較しない。
        # 能力・前提条件・Speech参照の変化は候補別の既存commit検査へ渡す。
        if (
            replace(
                current,
                activity_bindings=self.evidence.activity_bindings,
                capabilities=self.evidence.capabilities,
                preconditions=self.evidence.preconditions,
                capability_tokens=self.evidence.capability_tokens,
                memory_tokens=self.evidence.memory_tokens,
                precondition_tokens=self.evidence.precondition_tokens,
                communicative_goal_catalog=self.evidence.communicative_goal_catalog,
                speech_source_bindings=self.evidence.speech_source_bindings,
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
            *self.evidence.memory_tokens,
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
            communicative_goal_catalog=current.communicative_goal_catalog,
            speech_source_bindings=current.speech_source_bindings,
        )


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
