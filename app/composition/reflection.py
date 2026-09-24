"""実所有者の履歴を背景Reflectionと永続Memoryへ配送する。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from app.composition.execution_observation import SPEECH_OBSERVATION_SOURCE
from app.composition.memory_persistence import CoreMemoryOperation, CoreMemoryPersistenceBinding
from app.domain.activity_execution import ActivityExecutionAuthority, ActivityExecutionRecord
from app.domain.activity_execution.observation import ObservedExecutionFactRecord
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
    BrainWorkAdmission,
    BrainWorkEnvelope,
    BrainWorkPriority,
)
from app.domain.contracts import ExecutionStatus
from app.domain.contracts.common import freeze_json
from app.domain.memory import MemoryWriteResult
from app.domain.memory_reflection import (
    LLMReflectionProposalPort,
    LLMReflectionSupportPort,
    ReflectionAcceptancePolicy,
    ReflectionCandidateAuthority,
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionCoordinator,
    ReflectionLLMRolePolicy,
    ReflectionRunResult,
    ReflectionSourceEvidence,
    ReflectionSourceKind,
    ReflectionTrigger,
    ReflectionTriggerKind,
)
from app.infrastructure.persistence import PersistenceError, PersistenceFailureCode
from app.runtime.kernel import CancellationToken, RuntimeClock
from app.usecases.ports.llm import LLMRolePort


@dataclass(frozen=True, slots=True)
class CoreReflectionConfiguration:
    """意味方針は登録元が明示し、構成側で保存判断を補完しない。"""

    roles: ReflectionLLMRolePolicy
    acceptance: ReflectionAcceptancePolicy
    max_pending: int

    def __post_init__(self) -> None:
        if not isinstance(self.roles, ReflectionLLMRolePolicy) or not isinstance(
            self.acceptance, ReflectionAcceptancePolicy
        ):
            raise ValueError("振り返りには既存Ownerの方針を明示してください")
        if type(self.max_pending) is not int or not 1 <= self.max_pending <= 256:
            raise ValueError("振り返りの受付上限が不正です")


@dataclass(slots=True)
class CoreReflectionOperation:
    """取消後も、投入済み保存操作とOwner結果を呼出元へ残す。"""

    context: ReflectionContextSnapshot
    current_source: Callable[[], ReflectionSourceEvidence | None]
    result: ReflectionRunResult | None = None
    writes: tuple[CoreMemoryOperation[MemoryWriteResult], ...] = ()


class CoreReflectionDelivery:
    def __init__(
        self,
        brain: BrainIntegrationRuntime,
        memory: CoreMemoryPersistenceBinding,
        activities: ActivityExecutionAuthority,
        llm: LLMRolePort,
        clock: RuntimeClock,
        config: CoreReflectionConfiguration,
    ) -> None:
        self.brain, self.memory, self.activities = brain, memory, activities
        self.clock, self.config = clock, config
        self._pending: dict[str, CoreReflectionOperation] = {}
        self._admissions: dict[tuple[str, int | None], BrainWorkAdmission] = {}
        self.latest_admission: BrainWorkAdmission | None = None
        self.latest_operation: CoreReflectionOperation | None = None
        self.last_error: Exception | None = None
        self._owner = ReflectionCoordinator(
            LLMReflectionProposalPort(llm, config.roles, now=clock.now),
            LLMReflectionSupportPort(llm, config.roles, now=clock.now),
            ReflectionCandidateAuthority(config.acceptance),
            operational_policy=config.roles.operational,
            max_pending_tasks=config.max_pending,
            live_context=self._live_context,
        )
        brain.register_module(BrainIntegrationModule.REFLECTION, self)
        brain.register_terminal_observer(BrainIntegrationModule.REFLECTION, self.terminal)

    def _live_context(self, context: ReflectionContextSnapshot) -> ReflectionContextSnapshot | None:
        operation = self._pending.get(context.reflection_id)
        if operation is None or operation.current_source() != context.primary_sources[0]:
            return None
        return context

    @staticmethod
    def _activity_source(record: ActivityExecutionRecord) -> ReflectionSourceEvidence:
        return ReflectionSourceEvidence(
            record.result.command_id,
            ReflectionSourceKind.EXECUTION_FACT,
            "activity_execution",
            record.record_revision,
            record.result.occurred_at,
            freeze_json({
                "result": record.result.to_dict(),
                "effect_uncertainty": record.effect_uncertainty.value,
            }),
            (record.invocation.command.decision_id,),
        )

    @staticmethod
    def _presentation_source(record: ObservedExecutionFactRecord) -> ReflectionSourceEvidence:
        return ReflectionSourceEvidence(
            record.result.command_id,
            ReflectionSourceKind.PRESENTATION_FACT,
            "activity_execution",
            record.record_revision,
            record.result.occurred_at,
            freeze_json({
                "result": record.result.to_dict(),
                "execution_id": record.execution_id,
                "subject_ref": record.subject_ref,
                "effect_uncertainty": record.effect_uncertainty.value,
            }),
            (record.latest_observation_id, record.provenance.source_decision_id),
        )

    def observe_activity(self, work: BrainIntegrationWork, record: ActivityExecutionRecord) -> None:
        """前景への配送を待たせず、拒否・失敗を接続結果として保持する。"""
        if not record.terminal:
            return

        def current() -> ReflectionSourceEvidence | None:
            value = self.activities.snapshot(record.result.command_id)
            return None if value is None else self._activity_source(value)

        self._offer(work.envelope, lambda: self._activity_source(record), current)

    def observe_presentation(
        self, envelope: BrainWorkEnvelope, record: ObservedExecutionFactRecord
    ) -> None:
        if record.source != SPEECH_OBSERVATION_SOURCE:
            self.last_error = ValueError("Speechの受理済み観測だけを提示根拠にできます")
            return
        if record.result.status is ExecutionStatus.OBSERVABLE:
            return
        def current() -> ReflectionSourceEvidence | None:
            value = self.activities.observed_snapshot(
                record.source.source_contract_id, record.execution_id
            ).value
            return None if value is None else self._presentation_source(value)

        self._offer(envelope, lambda: self._presentation_source(record), current)

    def _offer(
        self,
        envelope: BrainWorkEnvelope,
        source: Callable[[], ReflectionSourceEvidence],
        current: Callable[[], ReflectionSourceEvidence | None],
    ) -> None:
        try:
            self.submit(envelope, source(), current)
        except Exception as error:
            self.last_error = error

    def submit(
        self,
        envelope: BrainWorkEnvelope,
        source: ReflectionSourceEvidence,
        current: Callable[[], ReflectionSourceEvidence | None],
    ) -> BrainWorkAdmission:
        if current() != source:
            raise ValueError("振り返り元が実Ownerの現在記録と一致しません")
        key = (source.source_ref, source.source_revision)
        previous = self._admissions.get(key)
        if previous is not None:
            return previous
        if len(self._pending) >= self.config.max_pending:
            raise ValueError("振り返りの受付上限へ到達しました")
        identity = uuid4().hex
        now = self.clock.now()
        policy = self.config.roles.operational
        trigger = ReflectionTrigger(
            identity, ReflectionTriggerKind.EPISODE_COMPLETED,
            (source.source_ref,), envelope.source_context_revision, 0, True, now,
        )
        context = ReflectionContextSnapshot(
            identity, trigger, (source,), (), envelope.source_context_revision,
            None, now, envelope.trace_id, policy.policy_id, policy.policy_revision,
        )
        operation = CoreReflectionOperation(context, current)
        work = BrainIntegrationWork(
            identity, BrainIntegrationModule.REFLECTION,
            BrainIntegrationLane.BACKGROUND_REFLECTION,
            BrainWorkEnvelope(
                envelope.trace_id, identity, envelope.source_event_ids,
                envelope.source_context_revision, None, None, BrainWorkPriority.BACKGROUND,
                now, root_trigger_id=envelope.root_trigger_id or envelope.trigger_id,
            ),
            operation,
        )
        self._pending[identity] = operation
        try:
            admission = self.brain.submit(work)
        except BaseException:
            self._pending.pop(identity, None)
            raise
        if not admission.accepted:
            self._pending.pop(identity, None)
        else:
            self._admissions[key] = admission
            # 完了済みの古い配送記録だけを有界に保持する。
            active = {
                (item.context.primary_sources[0].source_ref,
                 item.context.primary_sources[0].source_revision)
                for item in self._pending.values()
            }
            for old in tuple(self._admissions):
                if len(self._admissions) <= self.config.max_pending * 2:
                    break
                if old not in active:
                    del self._admissions[old]
        self.latest_operation, self.latest_admission = operation, admission
        return admission

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        return isinstance(work.payload, CoreReflectionOperation) and (
            work.payload.current_source() == work.payload.context.primary_sources[0]
        )

    async def execute(self, work: BrainIntegrationWork, cancellation: CancellationToken) -> object:
        operation = work.payload
        if not isinstance(operation, CoreReflectionOperation):
            raise ValueError("振り返り配送の型が不正です")
        task: asyncio.Task[ReflectionRunResult] | None = None
        try:
            if cancellation.cancelled:
                raise asyncio.CancelledError
            task = self._owner.submit(operation.context)
            operation.result = await task
            if cancellation.cancelled:
                raise asyncio.CancelledError
            if self._live_context(operation.context) is None:
                raise ValueError("保存前に振り返りの根拠が更新されました")
            for result in operation.result.results:
                if result.status is not ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION:
                    continue
                write = self.memory.submit_reflection(result)
                if write is None:
                    raise ValueError("採用された振り返りに候補がありません")
                operation.writes += (write,)
                stored = await write.wait()
                if stored.failure_code is not None:
                    raise PersistenceError(stored.failure_code, "振り返り候補の保存に失敗しました")
                if stored.value is None:
                    raise PersistenceError(
                        PersistenceFailureCode.UNAVAILABLE, "振り返り候補の保存結果がありません"
                    )
                if cancellation.cancelled:
                    raise asyncio.CancelledError
                if self._live_context(operation.context) is None:
                    raise ValueError("次の保存前に振り返りの根拠が更新されました")
            return operation
        finally:
            if task is not None and not task.done():
                task.cancel()
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
            self._pending.pop(work.work_id, None)

    def terminal(self, work: BrainIntegrationWork, outcome: object) -> None:
        """開始前取消・stale拒否でも受付記録を回収する。"""
        self._pending.pop(work.work_id, None)

    async def close(self) -> None:
        await self._owner.shutdown()
