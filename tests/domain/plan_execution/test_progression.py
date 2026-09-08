"""正規の計画・判断・活動所有者を通じた手順進行を検証する。"""

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionCoordinator,
    ActivityExecutionRecord,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionPreconditionState,
    ExecutionPreflightSnapshot,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import ExecutionStatus, PreconditionRef
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveOutcome,
    PlanExecutionIntentPayload,
    PlanProgressIntentPayload,
)
from app.domain.executive.requirements import RequirementSourcePublication
from app.domain.goal_planning import GoalPlanningAuthority, PlanFailurePolicy
from app.domain.goals import GoalCommitmentSnapshot, GoalCommitmentStore, InterruptionPolicy
from app.domain.plan_execution.contracts import PlanExecutionPolicy, PlanStepExecutionBinding
from app.domain.plan_execution.coordinator import PlanExecutionCoordinator
from app.domain.plan_execution.owner import (
    PlanArgumentFact,
    PlanExecutionCurrentState,
    PlanExecutionOwner,
    PlanExecutionStatus,
)
from app.domain.plan_execution.progress_contracts import PlanStepCompletionClaim
from app.runtime.kernel.clock import FakeRuntimeClock
from tests.domain.executive.test_executive import REVISIONS, candidate, live_state, snapshot
from tests.domain.executive.test_plan_authorization import inputs
from tests.domain.goal_planning.test_goal_planning import NOW, capability
from tests.domain.goal_planning.test_goal_planning import candidate as plan_candidate
from tests.domain.goal_planning.test_goal_planning import context as plan_context
from tests.domain.goal_planning.test_goal_planning import current as plan_current
from tests.helpers.executive_requirements import capture_plans, fence_clock, make_authority


@dataclass
class Setup:
    owner: PlanExecutionOwner
    planning: GoalPlanningAuthority
    goals: GoalCommitmentStore
    activity: ActivityExecutionAuthority
    scope_id: str
    current: PlanExecutionCurrentState
    clock: FakeRuntimeClock

    async def current_for(self, scope_id: str) -> PlanExecutionCurrentState:
        return self.current

    def assess(self) -> None:
        context = self.owner.observation(self.scope_id)
        self.clock.advance(1)
        claim = PlanStepCompletionClaim(
            context.observations[-1].step_id,
            ("condition-done",),
            (context.observations[-1].record.result.command_id,),
        )
        intent = ExecutiveIntent(
            "intent-progress",
            ExecutiveIntentKind.PLAN_PROGRESS,
            "実行結果から完了条件を評価する",
            PlanProgressIntentPayload(context.context_id, (claim,)),
            ("goal-1",),
        )
        captured = replace(
            snapshot(), plan_progress_contexts=(context,), captured_at=self.clock.now()
        )
        proposed = replace(
            candidate(),
            intents=(intent,),
            outcome=ExecutiveOutcome.CONTINUE_ACTIVITY,
            created_at=self.clock.now(),
        )
        current = replace(
            live_state(),
            plan_progress_contexts=(context,),
            requirements=(AuthoritativeIntentRequirements(intent.intent_id, (), ()),),
        )
        publication = self.owner.observation_publication(self.scope_id)
        captured = capture_plans(
            captured,
            (RequirementSourcePublication("progress", 1, publication.value, publication.tokens),),
        )
        assert captured.requirements_generation is not None
        current = captured.requirements_generation.owner.prepare(captured, proposed, current)
        with fence_clock(self.clock.now):
            decision = make_authority(captured).commit(
                proposed,
                captured,
                current=current,
                decision_id="assess-" + context.context_id,
                committed_at=self.clock.now(),
            )
        self.owner.apply_assessment(decision.plan_progress_assessments[0])


def setup(
    *,
    retry: bool = False,
    parallel: bool = False,
    capacity: int = 4,
    interruption: InterruptionPolicy = InterruptionPolicy.RESUMABLE,
) -> Setup:
    planning = GoalPlanningAuthority()
    captured = plan_context()
    original = plan_candidate()
    first = replace(
        original.steps[0], replan_on_failure=not retry, interruption_policy=interruption
    )
    second = replace(first, step_id="step-2", dependency_step_ids=() if parallel else ("step-1",))
    failure = PlanFailurePolicy.RETRY_BOUNDED if retry else PlanFailurePolicy.REPLAN_REQUIRED
    assert REVISIONS.goal_revision is not None
    assert captured.deterministic_directive is not None
    captured = replace(
        captured,
        revisions=REVISIONS,
        goal_context=replace(captured.goal_context, goal_revision=REVISIONS.goal_revision),
        deterministic_directive=replace(
            captured.deterministic_directive, steps=(first, second), failure_policy=failure
        ),
    )
    proposed = replace(original, revisions=REVISIONS, steps=(first, second), failure_policy=failure)
    plan = planning.commit(
        proposed,
        captured,
        replace(plan_current(), revisions=REVISIONS),
        plan_id="plan",
        committed_at=NOW,
    )
    assert REVISIONS.goal_revision is not None
    goals = GoalCommitmentStore(
        GoalCommitmentSnapshot(REVISIONS.goal_revision, (captured.goal,), (), NOW)
    )
    activity = ActivityExecutionAuthority()
    owner = PlanExecutionOwner(
        planning,
        goals,
        activity,
        PlanExecutionPolicy("execution", 1, 2, 2, capacity, 256),
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    )
    bindings = tuple(
        PlanStepExecutionBinding(
            step.step_id,
            step.operation_ref,
            step.target_ref,
            {"query": "資料"},
            ("goal-1",),
            (PreconditionRef("pre-ready", "equals", "target-1", True),),
        )
        for step in proposed.steps
    )
    facts = (PlanArgumentFact("goal-1", 1, {"query": "資料"}),)
    scope = owner.prepare_scope(
        plan, bindings, facts, captured_at=NOW, deadline_at=NOW + timedelta(minutes=1)
    )
    decision, context, current = inputs()
    decision = replace(
        decision,
        intents=(replace(decision.intents[0], payload=PlanExecutionIntentPayload(scope.scope_id)),),
    )
    context = replace(context, plan_scopes=(scope,))
    current = replace(current, plan_scopes=(scope,))
    publication = owner.scope_publication(scope.scope_id)
    context = capture_plans(
        context, (RequirementSourcePublication("scope", 1, publication.value, publication.tokens),)
    )
    assert context.requirements_generation is not None
    current = context.requirements_generation.owner.prepare(context, decision, current)
    with fence_clock(lambda: NOW):
        authorization = (
            make_authority(context)
            .commit(
                decision,
                context,
                current=current,
                decision_id="decision-plan",
                committed_at=NOW,
            )
            .plan_authorizations[0]
        )
    owner.activate(authorization, NOW)
    return Setup(
        owner,
        planning,
        goals,
        activity,
        scope.scope_id,
        PlanExecutionCurrentState(REVISIONS, facts),
        FakeRuntimeClock(NOW),
    )


class Preflight:
    def __init__(self, value: Setup) -> None:
        self.value = value

    async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
        return ExecutionPreflightSnapshot(
            self.value.current.revisions,
            (capability(),),
            (ExecutionPreconditionState("pre-ready", "target-1", "equals", True),),
            self.value.clock.now(),
        )


class Provider:
    def __init__(self, value: Setup, statuses: tuple[ExecutionStatus, ...] = ()) -> None:
        self.value = value
        self.statuses = statuses
        self.calls: list[ActivityInvocation] = []

    async def execute(
        self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
    ) -> tuple[ExecutionAdapterReport, ...]:
        self.calls.append(request.invocation)
        status = (
            self.statuses[len(self.calls) - 1]
            if len(self.calls) <= len(self.statuses)
            else ExecutionStatus.COMPLETED
        )
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                status,
                self.value.clock.now(),
                {},
            ),
        )


def runner(value: Setup, provider: Provider) -> PlanExecutionCoordinator:
    execution = ActivityExecutionCoordinator(
        Preflight(value), provider, value.activity, value.clock
    )
    return PlanExecutionCoordinator(value.owner, execution, value, value.clock)


@pytest.mark.asyncio
async def test_dependency_advances_only_after_owner_assessment() -> None:
    value = setup()
    provider = Provider(value)
    execution = runner(value, provider)
    first = await execution.advance(value.scope_id)
    assert first.status is PlanExecutionStatus.AWAITING_ASSESSMENT
    await execution.advance(value.scope_id)
    assert len(provider.calls) == 1
    value.assess()
    second = await execution.advance(value.scope_id)
    assert second.status is PlanExecutionStatus.AWAITING_ASSESSMENT
    assert len(provider.calls) == 2
    assert provider.calls[1].command.issued_at == value.clock.now()
    value.assess()
    assert value.owner.progress(value.scope_id).status is PlanExecutionStatus.COMPLETED
    await execution.advance(value.scope_id)
    assert len(provider.calls) == 2
    assert value.goals.snapshot().goals[0].status.value == "active"
    value.owner.retire(value.scope_id)
    assert value.activity.snapshot(provider.calls[0].command.command_id) is not None


@pytest.mark.asyncio
async def test_retry_is_bounded_and_keeps_each_attempt() -> None:
    value = setup(retry=True)
    provider = Provider(value, (ExecutionStatus.FAILED, ExecutionStatus.FAILED))
    execution = runner(value, provider)
    await execution.advance(value.scope_id)
    result = await execution.advance(value.scope_id)
    assert result.status is PlanExecutionStatus.FAILED
    await execution.advance(value.scope_id)
    assert len(provider.calls) == 2
    assert len(result.command_ids) == 2
    assert provider.calls[0].command.command_id != provider.calls[1].command.command_id


@pytest.mark.asyncio
async def test_changed_argument_evidence_stops_new_execution() -> None:
    value = setup()
    value.current = replace(
        value.current, argument_facts=(PlanArgumentFact("goal-1", 2, {"query": "別資料"}),)
    )
    provider = Provider(value)
    result = await runner(value, provider).advance(value.scope_id)
    assert result.status is PlanExecutionStatus.REPLAN_REQUIRED
    assert not provider.calls


class WaitingProvider(Provider):
    def __init__(self, value: Setup, *, count: int = 1) -> None:
        super().__init__(value)
        self.count = count
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cleanup = asyncio.Event()
        self.cancellations = 0

    async def execute(
        self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
    ) -> tuple[ExecutionAdapterReport, ...]:
        self.calls.append(request.invocation)
        if len(self.calls) == self.count:
            self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancellations += 1
            self.cleanup.set()
            await self.release.wait()
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.COMPLETED,
                self.value.clock.now(),
                {},
            ),
        )


@pytest.mark.asyncio
async def test_parallel_steps_and_duplicate_advance_do_not_duplicate_commands() -> None:
    value = setup(parallel=True)
    provider = WaitingProvider(value, count=2)
    execution = runner(value, provider)
    task = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        duplicate = await execution.advance(value.scope_id)
        assert duplicate.status is PlanExecutionStatus.RUNNING
        assert len(provider.calls) == 2
        assert len(set(duplicate.command_ids)) == 2
    finally:
        provider.release.set()
        await task
    assert value.owner.progress(value.scope_id).status is PlanExecutionStatus.AWAITING_ASSESSMENT


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", list(InterruptionPolicy))
async def test_repeated_cancellation_and_stop_wait_for_provider_cleanup(
    interruption: InterruptionPolicy,
) -> None:
    value = setup(interruption=interruption)
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    task = asyncio.create_task(execution.advance(value.scope_id))
    stopper: asyncio.Task[object] | None = None
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        task.cancel()
        if interruption is InterruptionPolicy.INTERRUPTIBLE:
            await asyncio.wait_for(provider.cleanup.wait(), 1)
        else:
            await asyncio.sleep(0)
        task.cancel()
        stopper = asyncio.create_task(execution.stop(value.scope_id))
        await asyncio.sleep(0)
        stopper.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not stopper.done()
        with pytest.raises(ValueError, match="開始予約または実行中"):
            value.owner.retire(value.scope_id)
        assert provider.cancellations == (
            1 if interruption is InterruptionPolicy.INTERRUPTIBLE else 0
        )
        provider.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stopper, 1)
        record = value.activity.snapshot(provider.calls[0].command.command_id)
        assert record is not None and record.result.status is ExecutionStatus.COMPLETED
        value.owner.retire(value.scope_id)
        assert value.activity.snapshot(record.result.command_id) == record
    finally:
        provider.release.set()
        await asyncio.gather(task, *(() if stopper is None else (stopper,)), return_exceptions=True)


@pytest.mark.asyncio
async def test_record_capacity_retains_previous_results() -> None:
    value = setup(capacity=1)
    provider = Provider(value)
    execution = runner(value, provider)
    await execution.advance(value.scope_id)
    value.assess()
    result = await execution.advance(value.scope_id)
    assert result.status is PlanExecutionStatus.CAPACITY_LIMIT
    assert len(provider.calls) == 1
    assert value.owner.observation(value.scope_id).observations[0].record.terminal


@pytest.mark.asyncio
async def test_expiry_after_current_state_wait_prevents_dispatch() -> None:
    value = setup()
    provider = Provider(value)

    class DelayedContext:
        async def current_for(self, scope_id: str) -> PlanExecutionCurrentState:
            value.clock.advance(61)
            return value.current

    activity = ActivityExecutionCoordinator(Preflight(value), provider, value.activity, value.clock)
    execution = PlanExecutionCoordinator(value.owner, activity, DelayedContext(), value.clock)
    result = await execution.advance(value.scope_id)
    assert result.status is PlanExecutionStatus.REPLAN_REQUIRED
    assert result.reason == "authorization_expired"
    assert not provider.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", [1, 2])
async def test_preflight_failure_releases_reservation_without_fabricating_execution(
    failure_at: int,
) -> None:
    value = setup()
    provider = Provider(value)

    class FailingPreflight(Preflight):
        calls = 0

        async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
            self.calls += 1
            if self.calls == failure_at:
                raise RuntimeError("現在状態の取得に失敗しました")
            return await super().current_for(invocation)

    activity = ActivityExecutionCoordinator(
        FailingPreflight(value), provider, value.activity, value.clock
    )
    execution = PlanExecutionCoordinator(value.owner, activity, value, value.clock)
    result = await execution.advance(value.scope_id)
    assert result.status in (PlanExecutionStatus.FAILED, PlanExecutionStatus.REPLAN_REQUIRED)
    assert not provider.calls
    record = value.activity.snapshot(result.command_ids[0])
    if failure_at == 1:
        assert record is None
    else:
        assert record is not None and record.result.status is ExecutionStatus.CANCELLED
    await execution.stop(value.scope_id)
    value.owner.retire(value.scope_id)


@pytest.mark.asyncio
async def test_terminal_record_does_not_release_dispatch_until_cleanup_finishes() -> None:
    value = setup()
    provider = Provider(value)
    finished = asyncio.Event()
    release = asyncio.Event()

    class DelayedCleanup(ActivityExecutionCoordinator):
        async def execute(self, invocation: ActivityInvocation) -> ActivityExecutionRecord:
            record = await super().execute(invocation)
            finished.set()
            await release.wait()
            return record

    activity = DelayedCleanup(Preflight(value), provider, value.activity, value.clock)
    execution = PlanExecutionCoordinator(value.owner, activity, value, value.clock)
    task = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(finished.wait(), 1)
        record = value.activity.snapshot(provider.calls[0].command.command_id)
        assert record is not None and record.terminal
        value.owner.stop(value.scope_id)
        with pytest.raises(ValueError, match="開始予約または実行中"):
            value.owner.retire(value.scope_id)
    finally:
        release.set()
        await task
    value.owner.retire(value.scope_id)


@pytest.mark.asyncio
async def test_provider_exception_does_not_retry_uncertain_effect() -> None:
    value = setup(retry=True)

    class FailingProvider(Provider):
        async def execute(
            self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
        ) -> tuple[ExecutionAdapterReport, ...]:
            self.calls.append(request.invocation)
            raise RuntimeError("外部処理の結果を取得できません")

    provider = FailingProvider(value)
    execution = runner(value, provider)
    result = await execution.advance(value.scope_id)
    assert result.status is PlanExecutionStatus.RECONCILIATION_REQUIRED
    await execution.advance(value.scope_id)
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_unrelated_argument_fact_does_not_invalidate_approval() -> None:
    value = setup()
    value.current = replace(
        value.current,
        argument_facts=(
            *value.current.argument_facts,
            PlanArgumentFact("unrelated", 12, "別の事実"),
        ),
    )
    provider = Provider(value)
    result = await runner(value, provider).advance(value.scope_id)
    assert result.status is PlanExecutionStatus.AWAITING_ASSESSMENT
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_missing_capability_preserves_typed_unavailable_result() -> None:
    value = setup()
    provider = Provider(value)

    class UnavailablePreflight(Preflight):
        async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return replace(await super().current_for(invocation), capabilities=())

    activity = ActivityExecutionCoordinator(
        UnavailablePreflight(value), provider, value.activity, value.clock
    )
    result = await PlanExecutionCoordinator(value.owner, activity, value, value.clock).advance(
        value.scope_id
    )
    assert not provider.calls
    record = value.activity.snapshot(result.command_ids[0])
    assert record is not None
    assert record.result.status is ExecutionStatus.UNSUPPORTED
    assert result.status is PlanExecutionStatus.REPLAN_REQUIRED


@pytest.mark.asyncio
async def test_repeated_authorization_does_not_restart_and_retired_authorization_is_rejected() -> (
    None
):
    value = setup()
    authorization = value.owner.observation(value.scope_id).authorization
    provider = Provider(value)
    execution = runner(value, provider)
    await execution.advance(value.scope_id)
    value.owner.activate(authorization, value.clock.now())
    await execution.advance(value.scope_id)
    assert len(provider.calls) == 1
    await execution.stop(value.scope_id)
    value.owner.retire(value.scope_id)
    with pytest.raises(ValueError, match="登録されていません"):
        value.owner.activate(authorization, value.clock.now())
