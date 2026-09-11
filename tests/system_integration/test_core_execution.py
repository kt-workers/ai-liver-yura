"""確定判断と既存実行Ownerから、実際の実行事実が認知へ戻る経路を検証する。"""

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from app.composition.execution import CoreExecutionDelivery
from app.domain.activity_execution import (
    ActivityExecutionCoordinator,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectUncertainty,
    ExecutionPreflightSnapshot,
)
from app.domain.brain_integration.runtime import BrainIntegrationWorkOutcome
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityAvailability, ExecutionStatus
from app.domain.goal_planning import GoalPlanningAuthority
from app.domain.input_gateway import InputPermission, InputSourceState
from app.domain.input_gateway.normalizer import InputAdmissionLedger, InputNormalizer
from app.domain.plan_execution.contracts import PlanExecutionPolicy
from app.domain.plan_execution.coordinator import PlanExecutionCoordinator
from app.domain.plan_execution.owner import PlanExecutionCurrentState, PlanExecutionOwner
from app.runtime.kernel.clock import FakeRuntimeClock
from tests.domain.activity_binding.test_binding import direct_fixture
from tests.domain.executive.test_executive import NOW
from tests.helpers.executive_requirements import fence_clock, make_authority
from tests.system_integration.test_core_cognition import application
from tests.system_integration.test_early_boot import work


@pytest.mark.asyncio
@pytest.mark.parametrize("additional_capability", [False, True])
@pytest.mark.parametrize(
    "result_kind", ["completed", "unavailable", "failed", "unknown", "possible", "cancelled"]
)
async def test_direct_actual_execution_returns_to_existing_cognition(
    monkeypatch: pytest.MonkeyPatch, additional_capability: bool, result_kind: str
) -> None:
    app, port = application(monkeypatch)
    _, _, _, captured, proposed, current = direct_fixture()
    if additional_capability:
        capabilities = (
            *captured.capabilities,
            replace(captured.capabilities[0], capability_id="capability-0"),
        )
        captured = replace(captured, capabilities=capabilities)
        current = replace(current, capabilities=capabilities)
    with fence_clock(lambda: NOW):
        decision = make_authority(captured).commit(
            proposed, captured, current=current, decision_id="execution-decision"
        )
    capabilities = captured.capabilities
    clock = FakeRuntimeClock(NOW)
    calls = []
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    class Preflight:
        async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
            return ExecutionPreflightSnapshot(
                invocation.command.revisions,
                () if result_kind == "unavailable" else capabilities,
                (),
                clock.now(),
            )

    class Adapter:
        async def execute(
            self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
        ) -> tuple[ExecutionAdapterReport, ...]:
            calls.append(request)
            if result_kind == "cancelled":
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0)
                    cleaned.set()
            return (
                ExecutionAdapterReport(
                    request.invocation.command.command_id,
                    request.invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.COMPLETED
                    if result_kind == "completed"
                    else ExecutionStatus.FAILED,
                    clock.now(),
                    {},
                    effect_uncertainty=(
                        ExecutionEffectUncertainty.UNKNOWN
                        if result_kind == "unknown"
                        else ExecutionEffectUncertainty.POSSIBLY_APPLIED
                        if result_kind == "possible"
                        else ExecutionEffectUncertainty.NONE
                    ),
                ),
            )

    class PlanContext:
        async def current_for(self, scope_id: str) -> PlanExecutionCurrentState:
            raise AssertionError("Direct試験で計画を開始してはいけません")

    activity = ActivityExecutionCoordinator(Preflight(), Adapter(), app.activities, clock)
    planning = GoalPlanningAuthority()
    plans = PlanExecutionOwner(
        planning,
        app.goals,
        app.activities,
        PlanExecutionPolicy("execution", 1, 2, 2, 4, 256),
        BOUNDS,
    )
    delivery = CoreExecutionDelivery(
        app.brain,
        activity,
        planning,
        plans,
        PlanExecutionCoordinator(plans, activity, PlanContext(), clock),
        app.input_context,
        InputNormalizer(InputAdmissionLedger(), bounds_policy=BOUNDS),
        InputSourceState(
            "activity_execution",
            "activity_execution",
            CapabilityAvailability.AVAILABLE,
            InputPermission.NOT_REQUIRED,
        ),
        lambda admission, root: app.cognition.submit_input(admission, root_trigger_id=root),
        clock,
        max_deliveries=16,
    )
    delivery.register()
    await app.start()
    try:
        parent = work()
        parent = replace(parent, envelope=replace(parent.envelope, root_trigger_id="original-root"))
        goals_before = app.goals.snapshot()
        delivery.accept_decision(parent, decision)
        delivery.accept_decision(parent, decision)
        if result_kind == "cancelled":
            await asyncio.wait_for(entered.wait(), 2)
            identity = next(iter(delivery._deliveries))
            assert app.brain.cancel(identity, "cancel")
            app.brain.cancel(identity, "cancel-again")
        outcomes = []
        for _ in range(3):
            outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
            assert outcome.status.value in {"completed", "cancelled"}, outcome
            outcomes.append(outcome)
        assert sum(o.status.value == "cancelled" for o in outcomes) == (result_kind == "cancelled")
        assert len(calls) == (0 if result_kind == "unavailable" else 1)
        record = app.activities.snapshot(next(iter(delivery._deliveries)))
        assert record is not None
        expected = {
            "completed": ExecutionStatus.COMPLETED,
            "unavailable": ExecutionStatus.UNSUPPORTED,
            "cancelled": ExecutionStatus.CANCELLED,
        }.get(result_kind, ExecutionStatus.FAILED)
        assert record.result.status is expected
        if result_kind in {"unknown", "possible"}:
            assert record.effect_uncertainty is (
                ExecutionEffectUncertainty.UNKNOWN
                if result_kind == "unknown"
                else ExecutionEffectUncertainty.POSSIBLY_APPLIED
            )
        if result_kind == "cancelled":
            assert cleaned.is_set()
        assert not activity._adapter_tasks
        assert not activity._signals
        assert app.goals.snapshot() == goals_before
        assert app.brain.trace(parent.envelope.trace_id).root_trigger_id == "original-root"
        assert outcomes[-1].result.candidate.source_event_ids
        assert record.bindings[0].capability_id == decision.activity_bindings[0].value.capability_id
    finally:
        await app.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "normal",
        "parallel",
        "retry",
        "uncertain",
        "replan",
        "stale",
        "cancel",
        "auxiliary",
        "resume",
    ],
)
async def test_plan_production_configuration_and_feedback(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from datetime import timedelta

    from app import bootstrap
    from app.composition.execution_configuration import CoreExecutionConfiguration
    from app.domain.contracts import PreconditionRef
    from app.domain.executive import PlanExecutionIntentPayload
    from app.domain.executive.requirements import RequirementSourcePublication
    from app.domain.plan_execution.owner import PlanExecutionStatus
    from tests.domain.executive.test_plan_authorization import inputs
    from tests.domain.goal_planning.test_goal_planning import _network
    from tests.domain.plan_execution.test_progression import (
        Preflight,
        Provider,
        WaitingProvider,
        setup,
    )
    from tests.helpers.executive_requirements import capture_plans

    value = setup(
        retry=mode in {"retry", "uncertain"},
        parallel=mode == "parallel",
        auxiliary=mode == "auxiliary",
    )
    value.clock.advance(10 * 86400)
    planning = value.planning
    plan = planning.current_plan("goal-1")
    assert plan is not None
    provider = (
        WaitingProvider(value, count=2 if mode == "parallel" else 1)
        if mode in {"parallel", "cancel", "resume"}
        else Provider(
            value,
            (ExecutionStatus.FAILED, ExecutionStatus.FAILED) if mode in {"retry", "replan"} else (),
        )
    )

    class PreflightWithAuxiliary(Preflight):
        async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
            current = await super().current_for(invocation)
            return (
                replace(current, capabilities=(*current.capabilities, _network("network-live")))
                if mode == "auxiliary"
                else current
            )

    class UncertainProvider(Provider):
        async def execute(
            self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
        ) -> tuple[ExecutionAdapterReport, ...]:
            self.calls.append(request.invocation)
            raise RuntimeError("試験用の提供先失敗")

    if mode == "uncertain":
        provider = UncertainProvider(value)
    config = CoreExecutionConfiguration(
        planning,
        PlanExecutionPolicy("execution", 1, 4, 2, 16, 256),
        value,
        PreflightWithAuxiliary(value),
        provider,
        InputNormalizer(InputAdmissionLedger(), bounds_policy=BOUNDS),
        InputSourceState(
            "activity_execution",
            "activity_execution",
            CapabilityAvailability.AVAILABLE,
            InputPermission.NOT_REQUIRED,
        ),
        (),
    )
    build = bootstrap.build_minimum_core
    monkeypatch.setattr(bootstrap, "GoalCommitmentStore", lambda: value.goals)
    monkeypatch.setattr(bootstrap, "ActivityExecutionAuthority", lambda: value.activity)
    monkeypatch.setattr(bootstrap, "SystemRuntimeClock", lambda: value.clock)
    monkeypatch.setattr(
        bootstrap,
        "build_minimum_core",
        lambda *a, **kw: build(
            *a, **{**kw, "cognition": replace(kw["cognition"], execution=config)}
        ),
    )
    app, _ = application(monkeypatch)
    delivery = app.cognition.execution
    assert isinstance(delivery, CoreExecutionDelivery)
    scope = delivery.prepare_plan(
        plan,
        (PreconditionRef("pre-ready", "equals", "target-1", True),),
        deadline_at=value.clock.now() + timedelta(minutes=1),
        source_event_id="plan-ready",
    )
    with pytest.raises(ValueError):
        delivery.plans.reserve_ready(scope.scope_id, value.current, value.clock.now())
    proposed, snapshot, current = inputs()
    proposed = replace(
        proposed,
        intents=(
            replace(
                proposed.intents[0],
                payload=PlanExecutionIntentPayload(scope.scope_id),
                required_capabilities=plan.candidate.steps[0].required_capabilities,
            ),
        ),
    )
    snapshot = replace(snapshot, plan_scopes=(scope,))
    current = replace(current, plan_scopes=(scope,))
    if mode == "auxiliary":
        snapshot = replace(snapshot, capabilities=(*snapshot.capabilities, _network()))
        current = replace(current, capabilities=(*current.capabilities, _network()))
    publication = delivery.plans.scope_publication(scope.scope_id)
    snapshot = capture_plans(
        snapshot, (RequirementSourcePublication("scope", 1, publication.value, publication.tokens),)
    )
    assert snapshot.requirements_generation is not None
    current = snapshot.requirements_generation.owner.prepare(snapshot, proposed, current)
    with fence_clock(lambda: value.clock.now()):
        decision = make_authority(snapshot).commit(
            proposed, snapshot, current=current, decision_id="approved-plan"
        )
    if mode == "stale":
        value.current = replace(
            value.current,
            argument_facts=tuple(
                replace(f, revision=f.revision + 1) for f in value.current.argument_facts
            ),
        )
    before = app.goals.snapshot()
    await app.start()
    try:
        parent = replace(work(), envelope=replace(work().envelope, root_trigger_id="plan-root"))
        delivery.accept_decision(parent, decision)
        delivery.accept_decision(parent, decision)
        if isinstance(provider, WaitingProvider):
            await asyncio.wait_for(provider.started.wait(), 2)
            if mode == "parallel":
                assert len(provider.calls) == 2
                provider.release.set()
            elif mode == "resume":
                from app.domain.executive import (
                    CommittedExecutiveDecision,
                    ExecutiveDecisionAuthority,
                )
                from tests.domain.plan_execution.test_resume import replacement

                value.owner = delivery.plans
                value.scope_id = scope.scope_id
                captured_decisions: list[CommittedExecutiveDecision] = []
                original_commit = ExecutiveDecisionAuthority.commit

                def capture_commit(
                    owner: ExecutiveDecisionAuthority, *args: Any, **kwargs: Any
                ) -> CommittedExecutiveDecision:
                    committed = original_commit(owner, *args, **kwargs)
                    captured_decisions.append(committed)
                    return committed

                monkeypatch.setattr(ExecutiveDecisionAuthority, "commit", capture_commit)
                resumed_scope = replacement(value, provider.calls[0].command.command_id)
                delivery.accept_decision(parent, captured_decisions[-1])
                delivery.accept_decision(parent, captured_decisions[-1])
                resumed = delivery.plans.observation(resumed_scope).authorization.scope.bindings[0]
                assert resumed.resumed_invocation == provider.calls[0]
                assert resumed.primary_binding == provider.calls[0].primary_binding
                assert len(provider.calls) == 1
                provider.release.set()
            else:
                identity = decision.plan_authorizations[0].authorization_id
                assert app.brain.cancel(identity, "cancel-plan")
                app.brain.cancel(identity, "repeat-cancel")
                provider.release.set()
        execution_outcome = None
        for _ in range(10):
            outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
            if outcome.module.value == "activity_execution":
                execution_outcome = outcome
                break
        assert execution_outcome is not None
        if mode != "cancel":
            assert execution_outcome.status.value == "completed", execution_outcome
        else:
            assert execution_outcome.status.value == "cancelled", execution_outcome
        progress = delivery.plans.progress(scope.scope_id)
        if mode == "retry":
            assert len(provider.calls) == 2 and progress.status is PlanExecutionStatus.FAILED
            assert provider.calls[0].primary_binding == provider.calls[1].primary_binding
        elif mode in {"uncertain", "replan", "stale"}:
            assert progress.status in {
                PlanExecutionStatus.REPLAN_REQUIRED,
                PlanExecutionStatus.RECONCILIATION_REQUIRED,
            }
            assert len(provider.calls) == (0 if mode == "stale" else 1)
        elif mode == "cancel":
            assert progress.status is PlanExecutionStatus.STOPPED
        else:
            assert progress.status is PlanExecutionStatus.AWAITING_ASSESSMENT
            assert len(provider.calls) == (2 if mode == "parallel" else 1)
        for request in provider.calls:
            assert request.primary_binding is not None
            assert (
                request.primary_binding.capability_id
                == plan.activity_bindings[0].value.capability_id
            )
        observations = delivery.plans.observation(scope.scope_id).observations
        assert all(o.record.terminal for o in observations)
        if mode == "uncertain":
            assert observations[0].record.effect_uncertainty is ExecutionEffectUncertainty.UNKNOWN
        if mode == "auxiliary":
            assert observations[0].record.bindings[1].capability_id == "network-live"
        assert not delivery.activity._adapter_tasks and not delivery.progression._tasks
        assert app.goals.snapshot() == before
        assert app.brain.trace(parent.envelope.trace_id).root_trigger_id == "plan-root"
        assert delivery._scope_events
        seen: list[BrainIntegrationWorkOutcome] = []
        for _ in range(12):
            try:
                followup = await asyncio.wait_for(app.brain.next_outcome(), 2)
            except asyncio.TimeoutError:
                pytest.fail(repr(seen))
            seen.append(followup)
            if followup.module.value == "executive" and followup.status.value == "completed":
                assert followup.result.candidate.source_event_ids
                break
        else:
            pytest.fail("計画の根拠が次の判断へ到達していません")

        if mode == "normal":
            from app.domain.executive import (
                ExecutiveIntent,
                ExecutiveIntentKind,
                ExecutiveOutcome,
                PlanProgressIntentPayload,
            )
            from app.domain.plan_execution.progress_contracts import PlanStepCompletionClaim
            from tests.domain.executive.test_executive import (
                candidate as executive_candidate,
            )
            from tests.domain.executive.test_executive import (
                live_state as executive_current,
            )
            from tests.domain.executive.test_executive import (
                snapshot as executive_snapshot,
            )

            for step_id in ("step-1", "step-2"):
                observation = delivery.plans.observation(scope.scope_id)
                record = next(o.record for o in observation.observations if o.step_id == step_id)
                claim = PlanStepCompletionClaim(
                    step_id, ("condition-done",), (record.result.command_id,)
                )
                intent = ExecutiveIntent(
                    "intent-" + step_id,
                    ExecutiveIntentKind.PLAN_PROGRESS,
                    "試験用の完了条件評価",
                    PlanProgressIntentPayload(observation.context_id, (claim,)),
                    ("goal-1",),
                )
                captured = replace(
                    executive_snapshot(),
                    plan_progress_contexts=(observation,),
                    captured_at=value.clock.now(),
                )
                candidate = replace(
                    executive_candidate(),
                    intents=(intent,),
                    outcome=ExecutiveOutcome.CONTINUE_ACTIVITY,
                    created_at=value.clock.now(),
                )
                progress_publication = delivery.plans.observation_publication(scope.scope_id)
                captured = capture_plans(
                    captured,
                    (
                        RequirementSourcePublication(
                            "progress", 1, progress_publication.value, progress_publication.tokens
                        ),
                    ),
                )
                assert captured.requirements_generation is not None
                current = captured.requirements_generation.owner.prepare(
                    captured,
                    candidate,
                    replace(executive_current(), plan_progress_contexts=(observation,)),
                )
                with fence_clock(value.clock.now):
                    assessed = make_authority(captured).commit(
                        candidate, captured, current=current, decision_id="assess-" + step_id
                    )
                delivery.accept_decision(parent, assessed)
                for _ in range(12):
                    observed = await asyncio.wait_for(app.brain.next_outcome(), 2)
                    if observed.module.value == "activity_execution":
                        assert observed.status.value == "completed", observed
                        break
                else:
                    pytest.fail("評価後の計画進行が配送されませんでした")
            assert delivery.plans.progress(scope.scope_id).status is PlanExecutionStatus.COMPLETED
            assert len(provider.calls) == 2
            assert app.goals.snapshot() == before
    finally:
        if isinstance(provider, WaitingProvider):
            provider.release.set()
        await app.stop()
