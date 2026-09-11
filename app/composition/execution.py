"""確定判断を既存実行Ownerへ配送し、実行事実だけを認知へ戻す。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.domain.activity_binding import ActivityExecutionBindingPublication
from app.domain.activity_binding.projector import direct_invocation, plan_execution_inputs
from app.domain.activity_execution import (
    ActivityExecutionCoordinator,
    ActivityExecutionRecord,
    ActivityInterruptibility,
    ActivityInvocation,
    CapabilityBinding,
)
from app.domain.activity_execution.projector import to_execution_event
from app.domain.brain_integration import (
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
    BrainWorkAdmission,
)
from app.domain.brain_integration.runtime import BrainIntegrationWorkOutcome
from app.domain.contracts import PreconditionRef, RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.contracts.finalization import FinalizationError
from app.domain.executive import CommittedExecutiveDecision
from app.domain.executive.contracts import ActivityIntentPayload, ExecutiveIntent
from app.domain.executive.projector import to_system_command
from app.domain.goal_planning import ActivityPlan, GoalPlanningAuthority
from app.domain.input_gateway import (
    InputAdmission,
    InputAdmissionStatus,
    InputModality,
    InputObservation,
    InputSourceState,
)
from app.domain.input_gateway.normalizer import InputNormalizer
from app.domain.input_meaning import ReferenceContextKind
from app.domain.plan_execution.contracts import PlanExecutionScope
from app.domain.plan_execution.coordinator import PlanExecutionCoordinator
from app.domain.plan_execution.owner import (
    PlanExecutionOwner,
    PlanExecutionProgress,
    PlanExecutionStatus,
)
from app.runtime.kernel import CancellationToken, RuntimeClock


@dataclass(frozen=True, slots=True)
class ExecutionFeedbackRetentionPolicy:
    """current cognition向けの実行事実参照数を明示する。"""

    policy_id: str
    policy_revision: int
    max_recent_actual_fact_refs: int

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("保持方針には空でない識別子が必要です")
        if type(self.policy_revision) is not int or self.policy_revision < 1:
            raise ValueError("保持方針のリビジョンは正の整数が必要です")
        if (
            type(self.max_recent_actual_fact_refs) is not int
            or self.max_recent_actual_fact_refs < 1
        ):
            raise ValueError("実行事実参照の保持上限は正の整数が必要です")


@dataclass(frozen=True, slots=True)
class ExecutionBrainPayload:
    decision: CommittedExecutiveDecision
    invocation: ActivityInvocation | None = None
    scope_id: str | None = None
    binding: ActivityExecutionBindingPublication | None = None


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
        retention_policy: ExecutionFeedbackRetentionPolicy,
    ) -> None:
        if plans.activity_authority is not activity.authority:
            raise ValueError("実行事実のOwnerが一致しません")
        if not isinstance(retention_policy, ExecutionFeedbackRetentionPolicy):
            raise ValueError("実行事実参照には型付き保持方針が必要です")
        self.brain, self.activity, self.planning, self.plans = brain, activity, planning, plans
        self.progression, self.reference, self.clock = progression, reference, clock
        self.normalizer, self.feedback_source, self.submit_input = (
            normalizer,
            feedback_source,
            submit_input,
        )
        self.retention_policy = retention_policy
        self._deliveries: dict[str, ExecutionBrainPayload] = {}
        self._feedback: dict[str, set[str]] = {}
        self._terminal_events: dict[str, tuple[str, PlanExecutionStatus]] = {}
        self._scope_events: dict[str, str] = {}
        self._plan_events: dict[str, str] = {}
        self._progress_feedback: dict[str, tuple[object, ...]] = {}
        self._sources_consumed: Callable[[], None] | None = None

    def register(self) -> None:
        self.brain.register_module(BrainIntegrationModule.ACTIVITY_EXECUTION, self)
        self.brain.register_terminal_observer(
            BrainIntegrationModule.ACTIVITY_EXECUTION, self._terminal
        )

    def _terminal(self, work: BrainIntegrationWork, outcome: BrainIntegrationWorkOutcome) -> None:
        self._deliveries.pop(work.work_id, None)

    def prepare_plan(
        self,
        plan: ActivityPlan,
        preconditions: tuple[PreconditionRef, ...],
        *,
        deadline_at: datetime,
        source_event_id: str,
    ) -> PlanExecutionScope:
        if source_event_id in self._plan_events:
            raise ValueError("計画の入力参照が重複しています")
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
                publications = tuple(
                    p
                    for p in result.activity_bindings
                    if p.value.binding_id == intent.payload.binding_ref
                )
                if len(publications) != 1:
                    raise ValueError("確定判断の正規bindingは一件だけ必要です")
                binding = publications[0]
                existing = self.activity.authority.snapshot(identity)
                if existing is not None:
                    self._require_same_direct(result, intent, binding, existing)
                    continue
                invocation = direct_invocation(
                    result,
                    intent,
                    command_id=identity,
                    invocation_id=f"invocation:{identity}",
                    requested_at=self.clock.now(),
                )
                self._submit(
                    work, identity, ExecutionBrainPayload(result, invocation, binding=binding)
                )
        for authorization in result.plan_authorizations:
            if authorization.authorization_id in self._deliveries:
                if self._deliveries[authorization.authorization_id].decision != result:
                    raise ValueError("同じ承認identityの内容が変更されています")
                continue
            scope = authorization.scope.scope_id
            try:
                existing_authorization = self.plans.observation(scope).authorization
            except ValueError:
                # 未承認登録だけをactivateする。retire済みscopeはOwnerが拒否する。
                self.plans.activate(authorization, self.clock.now())
            else:
                if existing_authorization != authorization:
                    raise ValueError("同じscopeの承認内容が変更されています")
                continue
            self._submit(
                work, authorization.authorization_id, ExecutionBrainPayload(result, scope_id=scope)
            )
        for assessment in result.plan_progress_assessments:
            identity = f"progress:{result.decision_id}:{assessment.intent_id}"
            if identity in self._deliveries:
                if self._deliveries[identity].decision != result:
                    raise ValueError("同じ評価identityの内容が変更されています")
                continue
            scope = assessment.context.authorization.scope.scope_id
            before = self.plans.progress(scope)
            after = self.plans.apply_assessment(assessment)
            if before == after:
                continue
            self._submit(
                work,
                f"progress:{result.decision_id}:{assessment.intent_id}",
                ExecutionBrainPayload(result, scope_id=scope),
            )

        self._consume_sources(result.candidate.source_event_ids)

    @staticmethod
    def _require_same_direct(
        decision: CommittedExecutiveDecision,
        intent: ExecutiveIntent,
        binding: ActivityExecutionBindingPublication,
        record: ActivityExecutionRecord,
    ) -> None:
        """再提示は現在性を再要求せず、既存Factの確定要求全体と照合する。"""
        value = binding.value
        old = record.invocation
        command = to_system_command(decision, intent, command_id=old.command.command_id)
        requirements = tuple(
            r
            for r in command.required_capabilities
            if r.capability_type == value.activity_type and r.operation == value.operation_ref
        )
        if len(requirements) != 1:
            raise ValueError("再提示のprimary要件が一致しません")
        expected = ActivityInvocation(
            f"invocation:{command.command_id}",
            command,
            value.operation_ref,
            value.arguments,
            ActivityInterruptibility(decision.candidate.interruptibility.value),
            old.requested_at,
            value.target_ref,
            CapabilityBinding(requirements[0], value.capability_id, value.capability_revision),
        )
        if old != expected:
            raise ValueError("同じcommand identityの確定要求内容が変更されています")

    def _consume_sources(self, source_event_ids: tuple[str, ...]) -> None:
        for event_id in source_event_ids:
            terminal = self._terminal_events.get(event_id)
            if terminal is not None:
                scope, status = terminal
                if self.plans.progress(scope).status is not status:
                    raise ValueError("消費した終端進行根拠が現在の状態と一致しません")
                # pending dispatchの有無は既存Ownerのretire契約で検査する。
                self.plans.retire(scope)
                self._feedback.pop(scope, None)
                self._progress_feedback.pop(scope, None)
                for correlations in (self._plan_events, self._scope_events):
                    for key in tuple(correlations):
                        if correlations[key] == scope:
                            del correlations[key]
                for key, value in tuple(self._terminal_events.items()):
                    if value[0] == scope:
                        del self._terminal_events[key]
            self._plan_events.pop(event_id, None)
            self._scope_events.pop(event_id, None)
        if self._sources_consumed is not None:
            self._sources_consumed()

    def _submit(
        self, parent: BrainIntegrationWork, identity: str, payload: ExecutionBrainPayload
    ) -> None:
        old = self._deliveries.get(identity)
        if old is not None:
            if old != payload:
                raise ValueError("同じ配送identityを異なる内容へ変更できません")
            return
        work = BrainIntegrationWork(
            identity,
            BrainIntegrationModule.ACTIVITY_EXECUTION,
            parent.lane,
            parent.envelope,
            payload,
            deadline_at=parent.deadline_at,
        )
        self._deliveries[identity] = payload
        try:
            admission = self.brain.submit(work)
            if not admission.accepted:
                raise ValueError("実行配送を受付できませんでした")
        except BaseException:
            self._deliveries.pop(identity, None)
            raise

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        payload = work.payload
        if not isinstance(payload, ExecutionBrainPayload):
            return False
        if payload.invocation is not None:
            if payload.binding is None:
                return False
            try:
                payload.binding.require_current()
            except FinalizationError:
                return False
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
        stopped_progress: PlanExecutionProgress | None = None
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
            stopped_progress = stop.result()
            raise
        finally:
            for observation in self.plans.observation(payload.scope_id).observations:
                if observation.record.terminal:
                    self.feedback(work, observation.record, payload.scope_id)
            if stopped_progress is not None:
                self.feedback_progress(work, payload.scope_id, stopped_progress)

    def feedback(
        self,
        work: BrainIntegrationWork,
        record: ActivityExecutionRecord,
        scope_id: str | None = None,
    ) -> None:
        command_id = record.result.command_id
        if not record.terminal or self.activity.authority.snapshot(command_id) != record:
            raise ValueError("還流にはOwnerの現在の終端実行事実が必要です")
        if scope_id is not None and any(
            command_id in commands for commands in self._feedback.values()
        ):
            # resumeで共有した同一Factも、active scopeの範囲で重複配送を抑止する。
            self._feedback.setdefault(scope_id, set()).add(command_id)
            return
        original = to_execution_event(
            record, event_id=f"execution:{command_id}", trace_id=work.envelope.trace_id
        )
        previous = self.reference.snapshot()
        command_ids = tuple(
            r.result.command_id for r in previous.activities if r.result.command_id != command_id
        )
        non_activity = sum(
            entry.kind is not ReferenceContextKind.ACTUAL_EXECUTION_FACT
            for entry in previous.context.entries
        )
        slots = min(
            self.retention_policy.max_recent_actual_fact_refs,
            max(0, previous.context.max_entries - non_activity),
        )
        recent = (*command_ids, command_id)
        self.reference.set_activity_references(recent[-slots:] if slots else ())
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
            self.reference.set_activity_references(
                tuple(r.result.command_id for r in previous.activities)
            )
            raise ValueError("実行事実の内部入力を受付できませんでした")
        if scope_id is not None and admission.event is not None:
            self._scope_events[admission.event.envelope.event_id] = scope_id
        try:
            if not self.submit_input(
                admission, work.envelope.root_trigger_id or work.envelope.trigger_id
            ).accepted:
                raise ValueError("実行事実の次の認知を受付できませんでした")
        except Exception:
            if admission.event is not None:
                self._scope_events.pop(admission.event.envelope.event_id, None)
            self.reference.set_activity_references(
                tuple(r.result.command_id for r in previous.activities)
            )
            raise
        if scope_id is not None:
            self._feedback.setdefault(scope_id, set()).add(command_id)

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
        if progress.status in {PlanExecutionStatus.COMPLETED, PlanExecutionStatus.STOPPED}:
            self._terminal_events[admission.event.envelope.event_id] = (scope_id, progress.status)
