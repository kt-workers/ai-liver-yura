"""承認済み計画の開始予約と、既存所有者の実行事実による進行を管理する。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import uuid4

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionEffectUncertainty,
)
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import (
    AuthorityRef,
    ExecutionStatus,
    IntentKind,
    IntentRef,
    RevisionVector,
    SystemCommand,
)
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
    utc_instant,
)
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityReadPublication,
    FinalizationError,
    FinalizationFailure,
    authority_mutation,
    authority_read_set,
)
from app.domain.goal_planning import ActivityPlan, GoalPlanningAuthority, PlanFailurePolicy
from app.domain.goals import (
    GoalCommitmentSnapshot,
    GoalCommitmentStore,
    GoalState,
    GoalStatus,
    InterruptionPolicy,
)

from .contracts import (
    PlanExecutionAuthorization,
    PlanExecutionPolicy,
    PlanExecutionScope,
    PlanStepExecutionBinding,
)
from .progress_contracts import (
    PlanExecutionObservation,
    PlanProgressAssessment,
    PlanProgressContext,
)


class GoalSnapshotPort(Protocol):
    def snapshot(self) -> GoalCommitmentSnapshot: ...


@dataclass(frozen=True, slots=True)
class PlanArgumentFact:
    reference_id: str
    revision: int
    value: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.reference_id, "reference_id")
        require_revision(self.revision, "revision")
        object.__setattr__(self, "value", freeze_json(self.value))


@dataclass(frozen=True, slots=True)
class PlanExecutionCurrentState:
    revisions: RevisionVector
    argument_facts: tuple[PlanArgumentFact, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("計画進行には依存先の現在のリビジョンが必要です")
        object.__setattr__(self, "argument_facts", _facts(self.argument_facts))


def _facts(values: tuple[PlanArgumentFact, ...]) -> tuple[PlanArgumentFact, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError("引数の由来は型付き事実の配列でなければなりません")
    result = tuple(values)
    if any(not isinstance(item, PlanArgumentFact) for item in result):
        raise ValueError("引数の由来には型付き事実が必要です")
    if len({item.reference_id for item in result}) != len(result):
        raise ValueError("引数の由来参照は重複できません")
    return result


class PlanExecutionStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    AWAITING_ASSESSMENT = "awaiting_assessment"
    COMPLETED = "completed"
    REPLAN_REQUIRED = "replan_required"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    RESUME_REQUIRED = "resume_required"
    FAILED = "failed"
    STOPPED = "stopped"
    CAPACITY_LIMIT = "capacity_limit"
    CONTEXT_REFRESH_REQUIRED = "context_refresh_required"


@dataclass(frozen=True, slots=True)
class PlanExecutionProgress:
    scope_id: str
    status: PlanExecutionStatus
    completed_step_ids: tuple[str, ...]
    command_ids: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlanExecutionBatch:
    invocations: tuple[ActivityInvocation, ...]
    progress: PlanExecutionProgress


@dataclass(slots=True)
class _RegisteredPlan:
    scope: PlanExecutionScope
    goal: GoalState
    argument_facts: tuple[PlanArgumentFact, ...]
    authorization: PlanExecutionAuthorization | None = None
    attempts: dict[str, list[ActivityInvocation]] = field(default_factory=dict)
    completed: set[str] = field(default_factory=set)
    stopped: bool = False
    last_confirmed_at: datetime | None = None
    blocked: tuple[PlanExecutionStatus, str] | None = None


class PlanExecutionOwner:
    def __init__(
        self,
        planning: GoalPlanningAuthority,
        goals: GoalSnapshotPort,
        activity: ActivityExecutionAuthority,
        policy: PlanExecutionPolicy,
        bounds_policy: BrainOperationalBoundsPolicy,
    ) -> None:
        if not isinstance(planning, GoalPlanningAuthority) or not isinstance(
            activity, ActivityExecutionAuthority
        ):
            raise ValueError("計画と活動の正規所有者が必要です")
        if not isinstance(policy, PlanExecutionPolicy) or not isinstance(
            bounds_policy, BrainOperationalBoundsPolicy
        ):
            raise ValueError("計画進行と判断の容量方針が必要です")
        self._planning = planning
        self._goals = goals
        self._activity = activity
        self._policy = policy
        self._bounds = bounds_policy
        self._epoch = uuid4().hex
        self._sequence = 0
        self._plans: dict[str, _RegisteredPlan] = {}
        self._finished_without_record: set[str] = set()
        self._dispatching: set[str] = set()
        self._participant = AuthorityFinalizationParticipant(
            self,
            "PlanExecutionOwner",
            20,
            supports_finalization=isinstance(goals, GoalCommitmentStore),
        )
        self._lock = self._participant
        if isinstance(goals, GoalCommitmentStore):
            self._participant.configure_dependencies(
                (
                    planning.finalization_participant,
                    goals.finalization_participant,
                    activity.finalization_participant,
                )
            )

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        """元所有者の読取と更新に共通する同期境界を公開する。"""
        return self._participant

    @property
    def activity_authority(self) -> ActivityExecutionAuthority:
        return self._activity

    @authority_mutation
    def prepare_scope(
        self,
        plan: ActivityPlan,
        bindings: tuple[PlanStepExecutionBinding, ...],
        argument_facts: tuple[PlanArgumentFact, ...],
        *,
        captured_at: datetime,
        deadline_at: datetime,
    ) -> PlanExecutionScope:
        if not isinstance(plan, ActivityPlan):
            raise ValueError("所有者が確定した計画が必要です")
        facts = _facts(argument_facts)
        if len(facts) > self._bounds.executive.max_fact_refs:
            raise ValueError("引数の由来事実が件数上限を超えています")
        size = len(
            json.dumps(
                [
                    {
                        "reference_id": f.reference_id,
                        "revision": f.revision,
                        "value": thaw_json(f.value),
                    }
                    for f in facts
                ],
                ensure_ascii=False,
            ).encode()
        )
        if size > self._bounds.executive.max_fact_payload_json_bytes:
            raise ValueError("引数の由来事実が容量上限を超えています")
        with self._lock:
            if len(self._plans) >= self._policy.max_active_plans:
                raise ValueError("計画の登録件数が上限へ到達しています")
            if self._planning.current_plan(plan.candidate.goal_id) != plan:
                raise ValueError("現在の登録済み計画だけを承認対象にできます")
            goal = self._goal(plan.candidate.goal_id)
            if (
                goal is None
                or goal.status is not GoalStatus.ACTIVE
                or goal.revision != plan.candidate.goal_state_revision
            ):
                raise ValueError("対象目標が現在の計画と一致しません")
            if any(item.scope.plan.plan_id == plan.plan_id for item in self._plans.values()):
                raise ValueError("同じ計画を重複登録できません")
            refs = {ref for binding in bindings for ref in binding.argument_fact_refs}
            if refs != {item.reference_id for item in facts}:
                raise ValueError("引数の必要な由来と登録事実が一致しません")
            self._sequence += 1
            scope = PlanExecutionScope(
                f"plan-scope-{self._epoch}-{self._sequence}",
                plan,
                bindings,
                captured_at,
                deadline_at,
                self._policy,
                self._bounds,
            )
            for binding in scope.bindings:
                resumed = binding.resumed_invocation
                if resumed is None:
                    continue
                record = self._activity.snapshot(resumed.command.command_id)
                known = any(
                    p.goal.goal_id == goal.goal_id
                    and any(resumed in values for values in p.attempts.values())
                    for p in self._plans.values()
                )
                if (
                    not known
                    or record is None
                    or record.terminal
                    or record.invocation != resumed
                    or utc_instant(record.result.occurred_at) > utc_instant(captured_at)
                ):
                    raise ValueError("同じ目標の所有済み非終端実行だけを再開対象にできます")
            self._plans[scope.scope_id] = _RegisteredPlan(scope, goal, facts)
            return scope

    @authority_mutation
    def activate(self, authorization: PlanExecutionAuthorization, now: datetime) -> None:
        require_aware(now, "now")
        if not isinstance(authorization, PlanExecutionAuthorization):
            raise ValueError("判断所有者による計画実行承認が必要です")
        with self._lock:
            item = self._require(authorization.scope.scope_id)
            if authorization.scope != item.scope:
                raise ValueError("承認対象と登録済みの範囲が一致しません")
            if item.authorization is not None:
                if item.authorization != authorization:
                    raise ValueError("同じ登録を別の承認で二重起動できません")
                return
            if not (
                utc_instant(authorization.committed_at)
                <= utc_instant(now)
                < utc_instant(item.scope.deadline_at)
            ):
                raise ValueError("承認を利用できる期間の外です")
            if not self._valid_target(item):
                raise ValueError("計画または対象目標が変更されています")
            item.authorization = authorization
            item.last_confirmed_at = now

    @authority_mutation
    def reserve_ready(
        self,
        scope_id: str,
        current: PlanExecutionCurrentState,
        now: datetime,
    ) -> PlanExecutionBatch:
        require_aware(now, "now")
        if not isinstance(current, PlanExecutionCurrentState):
            raise ValueError("現在の計画進行状態が必要です")
        with self._lock:
            item = self._require(scope_id)
            authorization = item.authorization
            if authorization is None:
                raise ValueError("未承認の計画から命令を発行できません")
            if item.last_confirmed_at is not None and utc_instant(now) < utc_instant(
                item.last_confirmed_at
            ):
                raise ValueError("承認より前に命令を発行できません")
            if not self._valid_target(item):
                item.blocked = (PlanExecutionStatus.REPLAN_REQUIRED, "plan_or_goal_changed")
            elif utc_instant(now) >= utc_instant(item.scope.deadline_at):
                item.blocked = (PlanExecutionStatus.REPLAN_REQUIRED, "authorization_expired")
            elif any(
                {f.reference_id: f for f in current.argument_facts}.get(expected.reference_id)
                != expected
                for expected in item.argument_facts
            ):
                item.blocked = (PlanExecutionStatus.REPLAN_REQUIRED, "argument_evidence_changed")
            elif current.revisions.goal_revision != self._goals.snapshot().revision:
                previous = self._progress(item)
                return PlanExecutionBatch(
                    (),
                    PlanExecutionProgress(
                        scope_id,
                        PlanExecutionStatus.CONTEXT_REFRESH_REQUIRED,
                        previous.completed_step_ids,
                        previous.command_ids,
                        "goal_context_changed",
                    ),
                )
            state = self._progress(item)
            if item.stopped or item.blocked is not None:
                return PlanExecutionBatch((), state)
            available = self._policy.max_inflight_steps - self._inflight_count()
            retained = sum(len(v) for p in self._plans.values() for v in p.attempts.values())
            bindings = {binding.step_id: binding for binding in item.scope.bindings}
            values: list[ActivityInvocation] = []
            for step in item.scope.plan.candidate.steps:
                if (
                    step.step_id in item.completed
                    or not set(step.dependency_step_ids) <= item.completed
                ):
                    continue
                attempts = item.attempts.get(step.step_id, [])
                if attempts:
                    record = self._activity.snapshot(attempts[-1].command.command_id)
                    if (
                        self._pending(attempts[-1])
                        or record is None
                        or not record.terminal
                        or record.result.status is ExecutionStatus.COMPLETED
                    ):
                        continue
                    if not self._retryable(item, step.step_id):
                        continue
                binding = bindings[step.step_id]
                if retained >= self._policy.max_retained_records:
                    return PlanExecutionBatch(tuple(values), self._progress(item, capacity=True))
                if binding.resumed_invocation is not None:
                    item.attempts[step.step_id] = [binding.resumed_invocation]
                    retained += 1
                    self._progress(item)
                    if item.blocked is not None:
                        break
                    continue
                if available <= 0:
                    break
                number = len(attempts) + 1
                command_id = f"{scope_id}:{step.step_id}:{number}"
                interruption = {
                    InterruptionPolicy.INTERRUPTIBLE: ActivityInterruptibility.INTERRUPTIBLE,
                    InterruptionPolicy.RESUMABLE: ActivityInterruptibility.SOFT_CANCEL_ONLY,
                    InterruptionPolicy.PROTECTED: ActivityInterruptibility.NON_INTERRUPTIBLE,
                }[step.interruption_policy]
                invocation = ActivityInvocation(
                    f"invocation:{command_id}",
                    SystemCommand(
                        command_id,
                        authorization.decision_id,
                        IntentRef(IntentKind.ACTIVITY, authorization.intent_id),
                        AuthorityRef(
                            "executive", "conscious_goal_action", authorization.decision_id
                        ),
                        now,
                        current.revisions,
                        item.scope.deadline_at,
                        binding.preconditions,
                        step.required_capabilities,
                    ),
                    binding.operation_ref,
                    binding.arguments,
                    interruption,
                    now,
                    binding.target_ref,
                )
                item.attempts.setdefault(step.step_id, []).append(invocation)
                self._dispatching.add(command_id)
                values.append(invocation)
                available -= 1
                retained += 1
            return PlanExecutionBatch(tuple(values), self._progress(item))

    def observation(self, scope_id: str) -> PlanProgressContext:
        with self._lock:
            return self._observation(self._require(scope_id))

    @authority_mutation
    def apply_assessment(self, assessment: PlanProgressAssessment) -> PlanExecutionProgress:
        if not isinstance(assessment, PlanProgressAssessment):
            raise ValueError("判断所有者の確定した完了評価が必要です")
        with self._lock:
            item = self._require(assessment.context.authorization.scope.scope_id)
            if assessment.context != self._observation(item):
                raise ValueError("完了評価の観測が現在の実行記録と一致しません")
            item.completed.update(claim.step_id for claim in assessment.claims)
            if item.last_confirmed_at is None or utc_instant(assessment.committed_at) > utc_instant(
                item.last_confirmed_at
            ):
                item.last_confirmed_at = assessment.committed_at
            return self._progress(item)

    @authority_mutation
    def progress(self, scope_id: str) -> PlanExecutionProgress:
        with self._lock:
            return self._progress(self._require(scope_id))

    @authority_mutation
    def stop(self, scope_id: str) -> PlanExecutionProgress:
        with self._lock:
            item = self._require(scope_id)
            item.stopped = True
            return self._progress(item)

    @authority_mutation
    def retire(self, scope_id: str) -> None:
        with self._lock:
            item = self._require(scope_id)
            if any(
                self._pending(invocation)
                for attempts in item.attempts.values()
                for invocation in attempts
            ):
                raise ValueError("開始予約または実行中の手順が残っています")
            if (
                not item.stopped
                and self._progress(item).status is not PlanExecutionStatus.COMPLETED
            ):
                raise ValueError("進行中の計画は停止または完了後に回収してください")
            self._finished_without_record.difference_update(
                invocation.command.command_id
                for values in item.attempts.values()
                for invocation in values
            )
            del self._plans[scope_id]

    @authority_mutation
    def _finish_dispatch(self, invocation: ActivityInvocation) -> None:
        """所有接続処理が呼出しを回収した後、未受付の予約を終える。"""
        with self._lock:
            self._dispatching.discard(invocation.command.command_id)
            if self._activity.snapshot(invocation.command.command_id) is not None:
                return
            for item in self._plans.values():
                if any(invocation in values for values in item.attempts.values()):
                    self._finished_without_record.add(invocation.command.command_id)
                    item.blocked = (PlanExecutionStatus.FAILED, "dispatch_not_admitted")
                    return
            raise ValueError("所有していない開始予約を終了できません")

    def _goal(self, goal_id: str) -> GoalState | None:
        return next((g for g in self._goals.snapshot().goals if g.goal_id == goal_id), None)

    def _valid_target(self, item: _RegisteredPlan) -> bool:
        return (
            self._goal(item.goal.goal_id) == item.goal
            and self._planning.current_plan(item.goal.goal_id) == item.scope.plan
        )

    def _require(self, scope_id: str) -> _RegisteredPlan:
        try:
            return self._plans[scope_id]
        except KeyError as error:
            raise ValueError("計画の承認対象が登録されていません") from error

    def _pending(self, invocation: ActivityInvocation) -> bool:
        record = self._activity.snapshot(invocation.command.command_id)
        return invocation.command.command_id not in self._finished_without_record and (
            invocation.command.command_id in self._dispatching
            or record is None
            or not record.terminal
        )

    def _inflight_count(self) -> int:
        return len(
            {
                invocation.command.command_id
                for p in self._plans.values()
                for values in p.attempts.values()
                for invocation in values
                if self._pending(invocation)
            }
        )

    def _retryable(self, item: _RegisteredPlan, step_id: str) -> bool:
        if any(
            b.step_id == step_id and b.resumed_invocation is not None for b in item.scope.bindings
        ):
            return False
        attempts = item.attempts[step_id]
        record = self._activity.snapshot(attempts[-1].command.command_id)
        step = next(step for step in item.scope.plan.candidate.steps if step.step_id == step_id)
        return (
            record is not None
            and record.result.status is ExecutionStatus.FAILED
            and not record.result.effect_refs
            and record.effect_uncertainty is ExecutionEffectUncertainty.NONE
            and item.scope.plan.candidate.failure_policy is PlanFailurePolicy.RETRY_BOUNDED
            and len(attempts) <= step.retry_limit
        )

    def _observation(self, item: _RegisteredPlan) -> PlanProgressContext:
        if item.authorization is None:
            raise ValueError("未承認の計画には実行観測がありません")
        values: list[PlanExecutionObservation] = []
        versions: list[str] = []
        for step in item.scope.plan.candidate.steps:
            attempts = item.attempts.get(step.step_id, [])
            if not attempts:
                continue
            record = self._activity.snapshot(attempts[-1].command.command_id)
            if record is not None:
                values.append(PlanExecutionObservation(step.step_id, len(attempts), record))
                versions.append(f"{step.step_id}:{len(attempts)}:{record.record_revision}")
        context_id = f"{item.scope.scope_id}:progress:" + ("|".join(versions) or "empty")
        return PlanProgressContext(context_id, item.authorization, tuple(values))

    def _progress(self, item: _RegisteredPlan, *, capacity: bool = False) -> PlanExecutionProgress:
        commands = tuple(i.command.command_id for values in item.attempts.values() for i in values)
        status = PlanExecutionStatus.READY
        reason = None
        for step in item.scope.plan.candidate.steps:
            attempts = item.attempts.get(step.step_id, [])
            if not attempts:
                continue
            record = self._activity.snapshot(attempts[-1].command.command_id)
            if record is None or not record.terminal:
                status = PlanExecutionStatus.RUNNING
            elif record.result.status is ExecutionStatus.COMPLETED:
                if step.step_id not in item.completed and status is not PlanExecutionStatus.RUNNING:
                    status = PlanExecutionStatus.AWAITING_ASSESSMENT
            elif not self._retryable(item, step.step_id):
                if (
                    record.result.effect_refs
                    or record.effect_uncertainty is not ExecutionEffectUncertainty.NONE
                ):
                    item.blocked = (
                        PlanExecutionStatus.RECONCILIATION_REQUIRED,
                        "execution_effect_requires_reconciliation",
                    )
                elif (
                    item.blocked is None
                    or item.blocked[0] is not PlanExecutionStatus.RECONCILIATION_REQUIRED
                ):
                    item.blocked = (
                        PlanExecutionStatus.REPLAN_REQUIRED
                        if step.replan_on_failure
                        else PlanExecutionStatus.FAILED,
                        "execution_failed",
                    )
        if len(item.completed) == len(item.scope.plan.candidate.steps):
            status = PlanExecutionStatus.COMPLETED
        elif capacity:
            status = PlanExecutionStatus.CAPACITY_LIMIT
        if item.blocked is not None:
            status, reason = item.blocked
        if item.stopped:
            status, reason = PlanExecutionStatus.STOPPED, "stop_requested"
        return PlanExecutionProgress(
            item.scope.scope_id, status, tuple(sorted(item.completed)), commands, reason
        )

    def scope_publication(self, scope_id: str) -> AuthorityReadPublication[PlanExecutionScope]:
        with authority_read_set(self._publication_participants()) as participants:
            item = self._require(scope_id)
            if item.stopped or not self._valid_target(item):
                raise FinalizationError(FinalizationFailure.TARGET_REJECTED)
            return AuthorityReadPublication(item.scope, tuple(p.token() for p in participants))

    def observation_publication(
        self, scope_id: str
    ) -> AuthorityReadPublication[PlanProgressContext]:
        with authority_read_set(self._publication_participants()) as participants:
            value = self._observation(self._require(scope_id))
            return AuthorityReadPublication(value, tuple(p.token() for p in participants))

    def _publication_participants(self) -> tuple[AuthorityFinalizationParticipant, ...]:
        if not isinstance(self._goals, GoalCommitmentStore):
            raise FinalizationError(FinalizationFailure.PARTICIPANT_UNSUPPORTED)
        return (self._participant, *self._participant.dependencies)
