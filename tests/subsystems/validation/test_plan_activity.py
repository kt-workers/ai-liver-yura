"""実行承認から事実還流までを共通Harnessと実製品Ownerで確認する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest

from app import bootstrap
from app.composition.execution import ExecutionFeedbackRetentionPolicy
from app.composition.execution_configuration import CoreExecutionConfiguration
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityAvailability, ExecutionStatus, PreconditionRef
from app.domain.executive import ExecutiveRequirementsOwner, PlanExecutionIntentPayload
from app.domain.executive.requirements import RequirementSourcePublication
from app.domain.input_gateway import InputPermission, InputSourceState
from app.domain.input_gateway.normalizer import InputAdmissionLedger, InputNormalizer
from app.domain.plan_execution.contracts import PlanExecutionPolicy
from app.subsystems.validation.contracts import (
    DelayInjection,
    FailureInjection,
    Gate,
    InjectedFailure,
    LabMode,
    RunStatus,
)
from app.subsystems.validation.plan_activity import (
    CommittedActivityLabCase,
    ObservedActivityPort,
    PlanActivityLabCase,
    plan_activity_target,
)
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from tests.domain.executive.test_plan_authorization import inputs
from tests.domain.plan_execution.test_progression import Preflight, Provider, WaitingProvider, setup
from tests.helpers.executive_requirements import capture_plans, fence_clock, make_authority
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec
from tests.system_integration.test_core_cognition import admission, application
from tests.system_integration.test_early_boot import work


def plan_setup(monkeypatch: pytest.MonkeyPatch, *, mode: str = "normal") -> Any:
    value = setup(retry=mode == "retry")
    value.clock.advance(10 * 86400)

    class CooperativeProvider(WaitingProvider):
        async def execute(self, request: Any, cancellation: Any) -> Any:
            self.started.set()
            while not cancellation.cancelled:
                await asyncio.sleep(0)
            self.cleanup.set()
            await self.release.wait()
            return await Provider.execute(self, request, cancellation)

    provider = (
        CooperativeProvider(value)
        if mode == "slow"
        else Provider(value, (ExecutionStatus.FAILED,) * 2 if mode == "retry" else ())
    )
    contexts: list[RunContext] = []

    class Adapter:
        async def execute(self, request: Any, cancellation: Any) -> Any:
            return await ObservedActivityPort(provider, contexts[-1], value.clock).execute(
                request, cancellation
            )

    class Current(Preflight):
        async def current_for(self, invocation: Any) -> Any:
            state = await super().current_for(invocation)
            return replace(state, capabilities=()) if mode == "unavailable" else state

    config = CoreExecutionConfiguration(
        value.planning,
        PlanExecutionPolicy("execution", 1, 4, 2, 16, 256),
        value,
        Current(value),
        Adapter(),
        InputNormalizer(InputAdmissionLedger(), bounds_policy=BOUNDS),
        InputSourceState(
            "activity_execution",
            "activity_execution",
            CapabilityAvailability.AVAILABLE,
            InputPermission.NOT_REQUIRED,
        ),
        (),
        ExecutionFeedbackRetentionPolicy("test-feedback", 1, 2),
    )
    monkeypatch.setattr(bootstrap, "GoalCommitmentStore", lambda **kw: value.goals)
    monkeypatch.setattr(bootstrap, "ActivityExecutionAuthority", lambda: value.activity)
    monkeypatch.setattr(bootstrap, "SystemRuntimeClock", lambda: value.clock)
    build = bootstrap.build_minimum_core

    def configured(*args: Any, **kwargs: Any) -> Any:
        cognition = kwargs["cognition"]
        generation = inputs()[1].requirements_generation
        assert generation is not None
        requirements = ExecutiveRequirementsOwner(BOUNDS)
        requirements.publish(generation.policy)
        return build(
            *args,
            **{
                **kwargs,
                "cognition": replace(cognition, execution=config, requirements=requirements),
            },
        )

    monkeypatch.setattr(bootstrap, "build_minimum_core", configured)
    app, port = application(monkeypatch)
    if mode == "input":
        return app, provider, value
    delivery = app.cognition.execution
    plan = value.planning.current_plan("goal-1")
    scope = delivery.prepare_plan(
        plan,
        (PreconditionRef("pre-ready", "equals", "target-1", True),),
        deadline_at=value.clock.now() + timedelta(minutes=1),
        source_event_id="plan-ready",
    )
    proposed, snapshot, current = inputs()
    proposed = replace(
        proposed,
        intents=(replace(proposed.intents[0], payload=PlanExecutionIntentPayload(scope.scope_id)),),
    )
    publication = delivery.plans.scope_publication(scope.scope_id)
    snapshot = capture_plans(
        replace(snapshot, plan_scopes=(scope,)),
        (RequirementSourcePublication("scope", 1, publication.value, publication.tokens),),
    )
    assert snapshot.requirements_generation is not None
    current = snapshot.requirements_generation.owner.prepare(
        snapshot, proposed, replace(current, plan_scopes=(scope,))
    )
    with fence_clock(value.clock.now):
        decision = make_authority(snapshot).commit(
            proposed, snapshot, current=current, decision_id="approved-plan"
        )
    parent = work()
    case = CommittedActivityLabCase(FIXTURE, parent, decision)
    fixture = replace(FIXTURE, typed_inputs=case.typed_inputs())
    case = replace(case, fixture=fixture)

    def factory(context: RunContext) -> Any:
        contexts.append(context)
        return app

    target = plan_activity_target(
        (case,), factory, PROVENANCE, "1", (), provenance_source=lambda: PROVENANCE
    )
    policy = replace(POLICY, timeout_seconds=3, max_intervals=100, max_export_bytes=1_000_000)
    runner = ValidationRunner((target,), policy)
    request = replace(spec(), mode=LabMode.INTEGRATED, target_module="plan_activity")
    return runner, request, fixture, app, provider, target, case, value, port


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "retry", "unavailable"])
async def test_real_plan_facts_and_feedback(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    runner, request, fixture, app, provider, _, _, value, _ = plan_setup(monkeypatch, mode=mode)
    goals = app.goals.snapshot()
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED, result
    assert result.machine_gate is Gate.FAIL
    output = cast(Any, result.stage_results[0].typed_outputs)
    execution = next(x for x in output["outcomes"] if x["module"] == "activity_execution")
    expected = {
        "normal": "awaiting_assessment",
        "retry": "failed",
        "unavailable": "replan_required",
    }
    assert execution["result"]["status"] == expected[mode]
    assert execution["result"]["completed_step_ids"] == ()
    assert len(provider.calls) == {"normal": 1, "retry": 2, "unavailable": 0}[mode]
    assert output["execution_records"]
    assert any(x["module"] == "executive" for x in output["outcomes"])
    assert any(
        any("execution:" in event for event in x["result"]["candidate"]["source_event_ids"])
        for x in output["outcomes"]
        if x["module"] == "executive" and x["result"] is not None
    )
    assert app.goals.snapshot() == goals
    assert runner.pending_count == 0 and not app.cognition.execution.activity._adapter_tasks
    assert result.export_json(1_000_000)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", list(InjectedFailure))
async def test_failure_injection_keeps_uncertain_effect(
    monkeypatch: pytest.MonkeyPatch, failure: InjectedFailure
) -> None:
    runner, request, fixture, _, provider, *_ = plan_setup(monkeypatch)
    request = replace(
        request, failure_injections=(FailureInjection("plan_activity.provider", failure, 1),)
    )
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED, result
    record = result.stage_results[0].typed_outputs["execution_records"][0]
    assert record["effect_uncertainty"] == "unknown"
    assert record["result"]["status"] != "completed"
    assert not provider.calls


@pytest.mark.asyncio
async def test_cancel_reaps_adapter_and_application(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, request, fixture, app, provider, *_ = plan_setup(monkeypatch, mode="slow")
    before = asyncio.all_tasks()
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(provider.started.wait(), 2)
    cancellation = asyncio.create_task(runner.cancel(request.run_id))
    await asyncio.wait_for(provider.cleanup.wait(), 2)
    provider.release.set()
    await cancellation
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert runner.pending_count == 0
    assert not app.cognition.execution.activity._adapter_tasks
    assert not (asyncio.all_tasks() - before - {asyncio.current_task()})


@pytest.mark.asyncio
async def test_delay_is_measured_at_adapter_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, request, fixture, *_ = plan_setup(monkeypatch)
    request = replace(
        request, delay_injections=(DelayInjection("plan_activity.provider", 0.02, 1),)
    )
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED, result
    interval = next(x for x in result.timeline if x.stage == "plan_activity.provider")
    assert interval.completed_ns - interval.started_ns >= 20_000_000


@pytest.mark.asyncio
async def test_provenance_mismatch_blocks_before_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    _, request, fixture, _, _, _, case, *_ = plan_setup(monkeypatch)

    def forbidden(context: RunContext) -> Any:
        raise AssertionError("来歴不一致では製品を起動できません")

    target = plan_activity_target(
        (case,),
        forbidden,
        PROVENANCE,
        "1",
        (),
        provenance_source=lambda: replace(PROVENANCE, git_head="b" * 40),
    )
    result = await ValidationRunner((target,), POLICY).run(request, fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert [interval.stage for interval in result.timeline] == ["target"]


@pytest.mark.asyncio
async def test_no_execution_owner_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = application(monkeypatch)
    case = PlanActivityLabCase(FIXTURE, admission(app))
    fixture = replace(FIXTURE, typed_inputs=case.typed_inputs())
    target = plan_activity_target(
        (replace(case, fixture=fixture),),
        lambda context: app,
        PROVENANCE,
        "1",
        (),
        provenance_source=lambda: PROVENANCE,
    )
    request = replace(spec(), mode=LabMode.INTEGRATED, target_module="plan_activity")
    result = await ValidationRunner((target,), POLICY).run(request, fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM


@pytest.mark.asyncio
async def test_input_entry_keeps_adopted_plan_and_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    app, provider, value = plan_setup(monkeypatch, mode="input")
    request = replace(spec(), mode=LabMode.INTEGRATED, target_module="plan_activity")
    case = PlanActivityLabCase(
        FIXTURE,
        admission(app, internal=True),
        "goal-1",
        "plan",
        (PreconditionRef("pre-ready", "equals", "target-1", True),),
        value.clock.now() + timedelta(minutes=1),
    )
    fixture = replace(FIXTURE, typed_inputs=case.typed_inputs())
    target = plan_activity_target(
        (replace(case, fixture=fixture),),
        lambda context: app,
        PROVENANCE,
        "1",
        (),
        provenance_source=lambda: PROVENANCE,
    )
    result = await ValidationRunner((target,), replace(POLICY, max_intervals=50)).run(
        request, fixture
    )
    assert result.status is RunStatus.COMPLETED, result
    assert result.machine_gate is Gate.PASS
    output = cast(Any, result.stage_results[0].typed_outputs)
    assert output["scope"]["plan"]["plan_id"] == "plan"
    assert output["execution_records"] == () and not provider.calls
    assert output["outcomes"][-1]["result"]["candidate"]["outcome"] == "wait"


@pytest.mark.asyncio
async def test_completion_assessment_is_exported_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.contracts.common import freeze_json
    from app.domain.llm import StructuredPayload
    from tests.system_integration.test_core_cognition import Port

    original = Port.invoke
    claimed: set[str] = set()

    async def assess(self: Any, request: Any) -> Any:
        result = await original(self, request)
        if request.role_id != "executive_deliberation":
            return result
        contexts = request.input.value["plan_progress_contexts"]
        if not contexts:
            return result
        context = contexts[0]
        observations = [o for o in context["observations"] if o["step_id"] not in claimed]
        if not observations:
            return result
        observation = observations[-1]
        claimed.add(observation["step_id"])
        assert result.output is not None
        payload = dict(cast(dict[str, Any], result.output.value))
        payload.update(
            outcome="continue_activity",
            intents=[
                {
                    "intent_id": "assess-" + observation["step_id"],
                    "kind": "plan_progress",
                    "purpose": "模擬LLMの完了条件評価",
                    "payload": {
                        "context_ref": context["context_id"],
                        "claims": [
                            {
                                "step_id": observation["step_id"],
                                "condition_refs": ["condition-done"],
                                "evidence_refs": [observation["result"]["command_id"]],
                            }
                        ],
                    },
                    "evidence_refs": ["goal-1"],
                    "required_capabilities": [],
                    "preconditions": [],
                    "forbidden_claim_refs": [],
                }
            ],
        )
        return replace(
            result, output=StructuredPayload(result.output.schema_id, freeze_json(payload))
        )

    monkeypatch.setattr(Port, "invoke", assess)
    runner, request, fixture, _, provider, _, _, value, _ = plan_setup(monkeypatch)
    with fence_clock(value.clock.now):
        result = await runner.run(request, fixture)
    output = result.stage_results[0].typed_outputs
    assert output is not None, result
    assessments = [
        a
        for o in output["outcomes"]
        if o["module"] == "executive" and o["result"] is not None
        for a in o["result"]["plan_progress_assessments"]
    ]
    assert len(assessments) == 2, output
    assert len(provider.calls) == 2
    assert any(
        o["module"] == "activity_execution" and o["result"]["status"] == "completed"
        for o in output["outcomes"]
    )
    assert len(output["execution_records"]) == 2
