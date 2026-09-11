"""確定判断を既存実行Ownerへ配送し、実行事実だけを認知へ戻す。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.domain.activity_binding.projector import direct_invocation, plan_execution_inputs
from app.domain.activity_execution import (
    ActivityExecutionCoordinator,
    ActivityExecutionRecord,
    ActivityInvocation,
)
from app.domain.activity_execution.projector import to_execution_event
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
    BrainWorkAdmission,
)
from app.domain.contracts import PreconditionRef, RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.executive import CommittedExecutiveDecision
from app.domain.executive.contracts import ActivityIntentPayload
from app.domain.goal_planning import ActivityPlan, GoalPlanningAuthority
from app.domain.input_gateway import (
    InputAdmission,
    InputAdmissionStatus,
    InputModality,
    InputObservation,
    InputSourceState,
)
from app.domain.input_gateway.normalizer import InputNormalizer
from app.domain.plan_execution.contracts import PlanExecutionScope
from app.domain.plan_execution.coordinator import PlanExecutionCoordinator
from app.domain.plan_execution.owner import (
    PlanExecutionOwner,
    PlanExecutionProgress,
    PlanExecutionStatus,
)
from app.runtime.kernel import CancellationToken, RuntimeClock


@dataclass(frozen=True, slots=True)
class ExecutionBrainPayload:
    decision: CommittedExecutiveDecision
    invocation: ActivityInvocation | None = None
    scope_id: str | None = None


class CoreExecutionDelivery:
    """Brainがtaskを所有し、提供先taskは既存Activity Coordinatorに残す。"""

    def __init__(
        self,
        brain: BrainIntegrationRuntime,
        activity: ActivityExecutionCoordinator,
        planning: GoalPlanningAuthority,
        plans: PlanExecutionOwner,
        progression: PlanExecutionCoordinator,
        reference: CoreInputReferenceContextBinding,
        normalizer: InputNormalizer,
        feedback_source: InputSourceState,
        submit_input: Callable[[InputAdmission, str | None], BrainWorkAdmission],
        clock: RuntimeClock,
        *,
        max_deliveries: int,
    ) -> None:
        if plans.activity_authority is not activity.authority:
            raise ValueError("実行事実のOwnerが一致しません")
        if type(max_deliveries) is not int or max_deliveries < 1:
            raise ValueError("配送保持上限は正の整数が必要です")
        self.brain, self.activity, self.planning, self.plans = brain, activity, planning, plans
        self.progression, self.reference, self.clock = progression, reference, clock
        self.normalizer, self.feedback_source, self.submit_input = (
            normalizer,
            feedback_source,
            submit_input,
        )
        self._limit = max_deliveries
        self._deliveries: dict[str, ExecutionBrainPayload] = {}
        self._feedback: set[str] = set()
        self._scope_events: dict[str, str] = {}
        self._plan_events: dict[str, str] = {}
        self._progress_feedback: dict[str, tuple[object, ...]] = {}

    def register(self) -> None:
        self.brain.register_module(BrainIntegrationModule.ACTIVITY_EXECUTION, self)

    def prepare_plan(
        self,
        plan: ActivityPlan,
        preconditions: tuple[PreconditionRef, ...],
        *,
        deadline_at: datetime,
        source_event_id: str,
    ) -> PlanExecutionScope:
        if source_event_id in self._plan_events or len(self._plan_events) >= self._limit:
            raise ValueError("計画の入力参照が重複または容量超過です")
        bindings, facts = plan_execution_inputs(
            plan, self.planning, preconditions, activities=self.activity.authority
        )
        scope = self.plans.prepare_scope(
            plan, bindings, facts, captured_at=self.clock.now(), deadline_at=deadline_at
        )

        self._plan_events[source_event_id] = scope.scope_id
        return scope

    def accept_decision(self, work: BrainIntegrationWork, result: object) -> None:
        if not isinstance(result, CommittedExecutiveDecision):
            raise ValueError("実行配送には確定済み判断が必要です")
        for intent in result.candidate.intents:
            if isinstance(intent.payload, ActivityIntentPayload):
                identity = uuid5(
                    NAMESPACE_URL, f"activity:{result.decision_id}:{intent.intent_id}"
                ).hex
                if identity in self._deliveries:
                    if self._deliveries[identity].decision != result:
                        raise ValueError("同じ判断identityの内容が変更されています")
                    continue
                invocation = direct_invocation(
                    result,
                    intent,
                    command_id=identity,
                    invocation_id=f"invocation:{identity}",
                    requested_at=self.clock.now(),
                )
                self._submit(work, identity, ExecutionBrainPayload(result, invocation))
        for authorization in result.plan_authorizations:
            if authorization.authorization_id in self._deliveries:
                if self._deliveries[authorization.authorization_id].decision != result:
                    raise ValueError("同じ承認identityの内容が変更されています")
                continue
            self.plans.activate(authorization, self.clock.now())
            scope = authorization.scope.scope_id
            self._submit(
                work, authorization.authorization_id, ExecutionBrainPayload(result, scope_id=scope)
            )
        for assessment in result.plan_progress_assessments:
            identity = f"progress:{result.decision_id}:{assessment.intent_id}"
            if identity in self._deliveries:
                if self._deliveries[identity].decision != result:
                    raise ValueError("同じ評価identityの内容が変更されています")
                continue
            self.plans.apply_assessment(assessment)
            scope = assessment.context.authorization.scope.scope_id
            self._submit(
                work,
                f"progress:{result.decision_id}:{assessment.intent_id}",
                ExecutionBrainPayload(result, scope_id=scope),
            )

    def _submit(
        self, parent: BrainIntegrationWork, identity: str, payload: ExecutionBrainPayload
    ) -> None:
        old = self._deliveries.get(identity)
        if old is not None:
            if old != payload:
                raise ValueError("同じ配送identityを異なる内容へ変更できません")
            return
        if len(self._deliveries) >= self._limit:
            raise ValueError("実行配送の保持容量を超えています")
        work = BrainIntegrationWork(
            identity,
            BrainIntegrationModule.ACTIVITY_EXECUTION,
            BrainIntegrationLane.BACKGROUND_REFLECTION,
            parent.envelope,
            payload,
            deadline_at=parent.deadline_at,
        )
        admission = self.brain.submit(work)
        if not admission.accepted:
            raise ValueError("実行配送を受付できませんでした")
        self._deliveries[identity] = payload

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        payload = work.payload
        if not isinstance(payload, ExecutionBrainPayload):
            return False
        if payload.invocation is not None:
            for publication in payload.decision.activity_bindings:
                publication.require_current()
        return True

    async def execute(self, work: BrainIntegrationWork, cancellation: CancellationToken) -> object:
        payload = work.payload
        if not isinstance(payload, ExecutionBrainPayload):
            raise ValueError("実行配送payloadの型が不正です")
        if cancellation.cancelled:
            raise asyncio.CancelledError
        if payload.invocation is not None:
            command_id = payload.invocation.command.command_id
            try:
                return await self.activity.execute(payload.invocation)
            finally:
                record = self.activity.authority.snapshot(command_id)
                if record is not None and record.terminal:
                    self.feedback(work, record)
        if payload.scope_id is None:
            raise ValueError("実行する承認scopeがありません")
        try:
            while True:
                progress = await self.progression.advance(payload.scope_id)
                for observation in self.plans.observation(payload.scope_id).observations:
                    if observation.record.terminal:
                        self.feedback(work, observation.record, payload.scope_id)
                if progress.status is not PlanExecutionStatus.READY:
                    self.feedback_progress(work, payload.scope_id, progress)
                    return progress
                if cancellation.cancelled:
                    raise asyncio.CancelledError
        except asyncio.CancelledError:
            stop = asyncio.create_task(self.progression.stop(payload.scope_id))
            while not stop.done():
                try:
                    await asyncio.shield(stop)
                except asyncio.CancelledError:
                    continue
            stop.result()
            raise
        finally:
            for observation in self.plans.observation(payload.scope_id).observations:
                if observation.record.terminal:
                    self.feedback(work, observation.record, payload.scope_id)

    def feedback(
        self,
        work: BrainIntegrationWork,
        record: ActivityExecutionRecord,
        scope_id: str | None = None,
    ) -> None:
        command_id = record.result.command_id
        if not record.terminal or self.activity.authority.snapshot(command_id) != record:
            raise ValueError("還流にはOwnerの現在の終端実行事実が必要です")
        if command_id in self._feedback:
            return
        if len(self._feedback) >= self._limit:
            raise ValueError("還流identity保持容量を超えています")
        original = to_execution_event(
            record, event_id=f"execution:{command_id}", trace_id=work.envelope.trace_id
        )
        previous = self.reference.snapshot()
        command_ids = tuple(
            r.result.command_id for r in previous.activities if r.result.command_id != command_id
        )
        self.reference.set_activity_references((*command_ids, command_id))
        current = self.reference.snapshot()
        observation = InputObservation(
            f"execution:{command_id}",
            self.feedback_source,
            InputModality.SUBSYSTEM,
            "activity_result",
            record.result.occurred_at,
            work.envelope.trace_id,
            RevisionVector(
                current.context.source_context_revision, current.goals.goal_revision, None
            ),
            freeze_json(original.to_dict()),
            correlation_id=record.invocation.command.decision_id,
        )
        admission = self.normalizer.normalize(observation)
        if admission.status is not InputAdmissionStatus.ACCEPTED:
            raise ValueError("実行事実の内部入力を受付できませんでした")
        if scope_id is not None and admission.event is not None:
            self._scope_events[admission.event.envelope.event_id] = scope_id
        if not self.submit_input(
            admission, work.envelope.root_trigger_id or work.envelope.trigger_id
        ).accepted:
            raise ValueError("実行事実の次の認知を受付できませんでした")
        self._feedback.add(command_id)

    def feedback_progress(
        self, work: BrainIntegrationWork, scope_id: str, progress: PlanExecutionProgress
    ) -> None:
        """計画Ownerの進行状態を根拠として渡し、実行成功へ変換しない。"""
        context = self.plans.observation(scope_id)
        signature = (
            context.context_id,
            progress.status,
            progress.completed_step_ids,
            progress.command_ids,
            progress.reason,
        )
        if self._progress_feedback.get(scope_id) == signature:
            return
        if len(self._scope_events) >= self._limit:
            raise ValueError("計画進行の還流保持容量を超えています")
        current = self.reference.snapshot()
        event_id = "plan-progress:" + uuid5(NAMESPACE_URL, repr((scope_id, signature))).hex
        admission = self.normalizer.normalize(
            InputObservation(
                event_id,
                self.feedback_source,
                InputModality.SUBSYSTEM,
                "plan_progress",
                self.clock.now(),
                work.envelope.trace_id,
                RevisionVector(
                    current.context.source_context_revision, current.goals.goal_revision, None
                ),
                freeze_json(
                    {
                        "scope_id": scope_id,
                        "status": progress.status.value,
                        "completed_step_ids": progress.completed_step_ids,
                        "command_ids": progress.command_ids,
                        "reason": progress.reason,
                        "context": context.to_dict(),
                    }
                ),
                correlation_id=context.authorization.decision_id,
            )
        )
        if admission.status is not InputAdmissionStatus.ACCEPTED or admission.event is None:
            raise ValueError("計画進行の正規内部入力を受付できませんでした")
        self._scope_events[admission.event.envelope.event_id] = scope_id
        if not self.submit_input(
            admission, work.envelope.root_trigger_id or work.envelope.trigger_id
        ).accepted:
            raise ValueError("計画進行の次の認知を受付できませんでした")
        self._progress_feedback[scope_id] = signature
