"""本体の現在文脈と状態所有者を、評価と同時確定の公開入口へつなぐ。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256

from app.composition.input_reference_context import (
    CoreInputReferenceContextBinding,
    CoreInputReferenceSnapshot,
)
from app.domain.appraisal import (
    AppraisalStateCommit,
    DeepAppraisalContext,
    DeepAppraisalFreshnessStamp,
    DeepAppraisalInterpreter,
    DeepAppraisalPolicy,
    InternalStateReducer,
    InternalStateSnapshot,
)
from app.domain.brain_integration import BrainIntegrationModule, BrainIntegrationWork
from app.domain.contracts import EventEnvelope
from app.domain.contracts.common import require_identifier
from app.domain.contracts.snapshots import (
    DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
    SnapshotGenerationSample,
    SnapshotReadCycle,
    SnapshotStabilizationPolicy,
    stabilize_snapshot,
)
from app.domain.input_meaning import StructuredInputMeaning
from app.runtime.kernel import CancellationToken, RuntimeClock
from app.usecases.ports.llm import LLMRolePort


@dataclass(frozen=True, slots=True)
class _CurrentAppraisalSources:
    reference: CoreInputReferenceSnapshot
    state: InternalStateSnapshot

    def generations(self) -> tuple[SnapshotGenerationSample, ...]:
        return tuple(
            SnapshotGenerationSample(owner, revision, sha256(repr(value).encode()).hexdigest())
            for owner, revision, value in (
                ("reference", self.reference.context.source_context_revision, self.reference),
                ("state", self.state.revision, self.state),
            )
        )


class CoreAppraisalBinding:
    """状態の判断を補わず、現在読取と確定済みの組の保持だけを所有する。"""

    def __init__(
        self,
        reference: CoreInputReferenceContextBinding,
        state: InternalStateReducer,
        llm: LLMRolePort,
        policy: DeepAppraisalPolicy,
        clock: RuntimeClock,
        *,
        stabilization: SnapshotStabilizationPolicy = DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
    ) -> None:
        if not isinstance(reference, CoreInputReferenceContextBinding):
            raise ValueError("評価には本体の入力参照接続が必要です")
        if not isinstance(state, InternalStateReducer):
            raise ValueError("評価には既存の状態所有者が必要です")
        if not isinstance(policy, DeepAppraisalPolicy):
            raise ValueError("評価には型付きの実行方針が必要です")
        if not isinstance(stabilization, SnapshotStabilizationPolicy):
            raise ValueError("評価の読取には型付き安定化方針が必要です")
        self._reference = reference
        self._state = state
        self._clock = clock
        self._stabilization = stabilization
        self._interpreter = DeepAppraisalInterpreter(llm, self, policy)
        self._latest: AppraisalStateCommit | None = None

    def _read(self) -> _CurrentAppraisalSources:
        return _CurrentAppraisalSources(self._reference.snapshot(), self._state.snapshot())

    def _read_cycle(self) -> SnapshotReadCycle[_CurrentAppraisalSources]:
        before, after = self._read(), self._read()
        return SnapshotReadCycle(
            before,
            before.generations(),
            after.generations(),
            self._stabilization.policy_id,
            self._stabilization.policy_revision,
        )

    def _current(self) -> _CurrentAppraisalSources:
        return stabilize_snapshot(self._stabilization, self._read_cycle)

    async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
        current = self._current()
        return DeepAppraisalFreshnessStamp(
            current.reference.context.source_context_revision, current.state.revision
        )

    def is_current_context(self, revision: int) -> bool:
        return self._current().reference.context.source_context_revision == revision

    def latest_commit(self) -> AppraisalStateCommit | None:
        """最後の成功結果を履歴として返し、現在性は主張しない。"""
        return self._latest

    def current_commit(self) -> AppraisalStateCommit | None:
        """状態または文脈が進んだ結果を、現在の評価事実として返さない。"""
        current, latest = self._current(), self._latest
        if latest is None:
            return None
        if (
            latest.internal_state != current.state
            or latest.appraisal_facts.source_context_revision
            != current.reference.context.source_context_revision
        ):
            return None
        return latest

    async def appraise(
        self,
        event: EventEnvelope,
        meaning: StructuredInputMeaning | None,
        *,
        request_id: str,
        cancellation: CancellationToken,
    ) -> AppraisalStateCommit:
        if cancellation.cancelled:
            raise asyncio.CancelledError
        current = self._current()
        if (
            event.revisions.source_context_revision
            != current.reference.context.source_context_revision
        ):
            raise ValueError("評価入力の文脈が現在の参照文脈と一致しません")
        context = DeepAppraisalContext(
            tuple(dict.fromkeys(entry.subject_ref for entry in current.reference.context.entries))
        )
        task = asyncio.create_task(
            self._interpreter.appraise(
                event,
                meaning,
                current.state,
                context,
                request_id=request_id,
                trace_id=event.trace_id,
                created_at=self._clock.now(),
            )
        )
        try:
            candidate = await asyncio.shield(task)
        except asyncio.CancelledError:
            # 提供先が取消を捕捉して結果を返しても、回収だけを行い確定しない。
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
        if cancellation.cancelled:
            raise asyncio.CancelledError
        current = self._current()
        revision = 1 if self._latest is None else self._latest.appraisal_facts.revision + 1
        committed = self._state.commit_with_facts(
            candidate,
            current_source_context_revision=current.reference.context.source_context_revision,
            committed_at=self._clock.now(),
            facts_revision=revision,
        )
        self._latest = committed
        return committed


@dataclass(frozen=True, slots=True)
class AppraisalBrainWorkPayload:
    event: EventEnvelope
    meaning: StructuredInputMeaning | None
    request_id: str


class AppraisalBrainModulePort:
    """既存Brain実行の有界な処理受付と取消・停止へ評価を登録する。"""

    def __init__(self, binding: CoreAppraisalBinding) -> None:
        self._binding = binding

    @staticmethod
    def _validate(work: BrainIntegrationWork) -> AppraisalBrainWorkPayload:
        payload = work.payload
        if not isinstance(payload, AppraisalBrainWorkPayload) or not isinstance(
            payload.event, EventEnvelope
        ):
            raise ValueError("評価の構成入力が不正です")
        require_identifier(payload.request_id, "request_id")
        if payload.meaning is not None and not isinstance(payload.meaning, StructuredInputMeaning):
            raise ValueError("評価へ渡す入力意味が不正です")
        if (
            work.module is not BrainIntegrationModule.APPRAISAL
            or work.envelope.source_event_ids != (payload.event.event_id,)
            or work.envelope.trace_id != payload.event.trace_id
            or work.envelope.source_context_revision
            != payload.event.revisions.source_context_revision
        ):
            raise ValueError("評価処理の入力と識別子・文脈・追跡識別子が一致しません")
        return payload

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        payload = self._validate(work)
        return self._binding.is_current_context(payload.event.revisions.source_context_revision)

    async def execute(
        self,
        work: BrainIntegrationWork,
        cancellation: CancellationToken,
    ) -> AppraisalStateCommit:
        payload = self._validate(work)
        return await self._binding.appraise(
            payload.event,
            payload.meaning,
            request_id=payload.request_id,
            cancellation=cancellation,
        )
