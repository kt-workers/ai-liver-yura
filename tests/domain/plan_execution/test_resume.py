"""同じ目標の再計画が進行中の活動を二重発行せず引き継ぐことを確認する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.activity_execution import (
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
)
from app.domain.contracts import ExecutionStatus
from app.domain.executive import PlanExecutionIntentPayload
from app.domain.executive.requirements import RequirementSourcePublication
from app.domain.goal_planning import ActivityContextRef
from app.domain.plan_execution.owner import PlanExecutionOwner, PlanExecutionStatus
from tests.domain.executive.test_plan_authorization import inputs
from tests.domain.goal_planning.test_goal_planning import context, current
from tests.domain.plan_execution.test_progression import (
    Preflight,
    Setup,
    WaitingProvider,
    runner,
    setup,
)
from tests.helpers.executive_requirements import capture_plans, fence_clock, make_authority


def replacement(
    value: Setup, command_id: str, *, registration_owner: PlanExecutionOwner | None = None
) -> str:
    owner = registration_owner or value.owner
    previous = value.planning.current_plan("goal-1")
    assert previous is not None
    original_scope = value.owner.observation(value.scope_id).authorization.scope
    record = value.activity.snapshot(command_id)
    assert record is not None
    step = replace(previous.candidate.steps[0], resume_activity_id=command_id)
    candidate = replace(previous.candidate, candidate_id="replacement", steps=(step,))
    captured = context()
    assert captured.deterministic_directive is not None
    captured = replace(
        captured,
        revisions=value.current.revisions,
        goal_context=replace(captured.goal_context, goal_revision=value.goals.snapshot().revision),
        previous_plan=previous,
        activities=(
            ActivityContextRef(command_id, "goal-1", step.operation_ref, record.result.status),
        ),
        deterministic_directive=replace(
            captured.deterministic_directive,
            steps=(step,),
            failure_policy=previous.candidate.failure_policy,
        ),
    )
    plan = value.planning.commit(
        candidate,
        captured,
        replace(current(), revisions=value.current.revisions, previous_plan=previous),
        plan_id="replacement",
        committed_at=value.clock.now(),
    )
    scope = owner.prepare_scope(
        plan,
        (replace(original_scope.bindings[0], resumed_invocation=record.invocation),),
        value.current.argument_facts,
        captured_at=value.clock.now(),
        deadline_at=value.clock.now() + timedelta(seconds=50),
    )
    proposed, snapshot, live = inputs()
    proposed = replace(
        proposed,
        intents=(replace(proposed.intents[0], payload=PlanExecutionIntentPayload(scope.scope_id)),),
    )
    publication = owner.scope_publication(scope.scope_id)
    snapshot = capture_plans(
        replace(snapshot, plan_scopes=(scope,)),
        (RequirementSourcePublication("scope", 1, publication.value, publication.tokens),),
    )
    assert snapshot.requirements_generation is not None
    live = snapshot.requirements_generation.owner.prepare(
        snapshot, proposed, replace(live, plan_scopes=(scope,))
    )
    with fence_clock(value.clock.now):
        authorization = (
            make_authority(snapshot)
            .commit(
                proposed,
                replace(snapshot, plan_scopes=(scope,)),
                current=replace(live, plan_scopes=(scope,)),
                decision_id="replacement-approval",
                committed_at=value.clock.now(),
            )
            .plan_authorizations[0]
        )
    owner.activate(authorization, value.clock.now())
    return scope.scope_id


@pytest.mark.asyncio
async def test_replanning_observes_existing_execution_without_second_dispatch() -> None:
    value = setup()
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        command_id = provider.calls[0].command.command_id
        new_scope = replacement(value, command_id)
        progress = await execution.advance(new_scope)
        assert progress.status is PlanExecutionStatus.RUNNING
        assert progress.command_ids == (command_id,)
        assert len(provider.calls) == 1
        await execution.advance(new_scope)
        assert len(provider.calls) == 1
        provider.release.set()
        await original
        assert value.owner.progress(new_scope).status is PlanExecutionStatus.AWAITING_ASSESSMENT
        observed = value.owner.observation(new_scope)
        assert observed.observations[0].record.invocation == provider.calls[0]
        assert observed.observations[0].record.invocation.command.decision_id == "decision-plan"
        value.scope_id = new_scope
        value.assess()
        assert value.owner.progress(new_scope).status is PlanExecutionStatus.COMPLETED
        assert value.goals.snapshot().goals[0].status.value == "active"
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
async def test_stopping_observation_does_not_cancel_source_owned_execution() -> None:
    value = setup()
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        new_scope = replacement(value, provider.calls[0].command.command_id)
        await execution.advance(new_scope)
        await execution.stop(new_scope)
        assert not original.done()
        assert provider.cancellations == 0
        with pytest.raises(ValueError, match="開始予約または実行中"):
            value.owner.retire(new_scope)
        provider.release.set()
        await original
        value.owner.retire(new_scope)
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
async def test_resumed_observation_rejects_a_different_original_command() -> None:
    value = setup()
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        new_scope = replacement(value, provider.calls[0].command.command_id)
        await execution.advance(new_scope)
        observation = value.owner.observation(new_scope)
        observed = observation.observations[0]
        record = observed.record
        invocation = replace(
            record.invocation,
            invocation_id="other-invocation",
            command=replace(record.invocation.command, command_id="other"),
        )
        different = value.activity.admit(
            invocation, await Preflight(value).current_for(invocation)
        ).record
        with pytest.raises(ValueError, match="既存要求と観測"):
            replace(observation, observations=(replace(observed, record=different),))
        assert value.owner.observation(new_scope) == observation
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
async def test_resumed_scope_cannot_change_the_original_arguments() -> None:
    value = setup()
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        new_scope = replacement(value, provider.calls[0].command.command_id)
        scope = value.owner.observation(new_scope).authorization.scope
        binding = scope.bindings[0]
        assert binding.resumed_invocation is not None
        changed = replace(binding.resumed_invocation, arguments={"query": "別の要求"})
        with pytest.raises(ValueError, match="再開対象の要求"):
            replace(scope, bindings=(replace(binding, resumed_invocation=changed),))
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
async def test_unowned_execution_cannot_be_registered_by_matching_request_alone() -> None:
    value = setup()
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    scope = value.owner.observation(value.scope_id).authorization.scope
    stranger = PlanExecutionOwner(
        value.planning, value.goals, value.activity, scope.policy, scope.bounds_policy
    )
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        with pytest.raises(ValueError, match="所有済み非終端実行"):
            replacement(value, provider.calls[0].command.command_id, registration_owner=stranger)
        assert len(provider.calls) == 1
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
async def test_completion_between_registration_and_attachment_is_preserved() -> None:
    value = setup()
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        new_scope = replacement(value, provider.calls[0].command.command_id)
        provider.release.set()
        await original
        result = await execution.advance(new_scope)
        assert result.status is PlanExecutionStatus.AWAITING_ASSESSMENT
        assert len(provider.calls) == 1
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_existing_activity_is_not_reissued_as_a_new_attempt() -> None:
    value = setup(retry=True)

    class FailingProvider(WaitingProvider):
        async def execute(
            self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
        ) -> tuple[ExecutionAdapterReport, ...]:
            reports = await super().execute(request, cancellation)
            return (replace(reports[0], status=ExecutionStatus.FAILED),)

    provider = FailingProvider(value)
    execution = runner(value, provider)
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        new_scope = replacement(value, provider.calls[0].command.command_id)
        await execution.advance(new_scope)
        provider.release.set()
        await original
        result = await execution.advance(new_scope)
        assert result.status is PlanExecutionStatus.FAILED
        await execution.advance(new_scope)
        assert len(provider.calls) == 1
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "id", "revision", "requirement"])
async def test_resume_rejects_changed_exact_primary(case: str) -> None:
    value = setup()
    provider = WaitingProvider(value)
    execution = runner(value, provider)
    original = asyncio.create_task(execution.advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        resumed_scope_id = replacement(value, provider.calls[0].command.command_id)
        scope = value.owner.observation(resumed_scope_id).authorization.scope
        binding = scope.bindings[0]
        resumed = binding.resumed_invocation
        assert resumed is not None and resumed.primary_binding is not None
        primary = resumed.primary_binding
        if case == "missing":
            altered = replace(resumed, primary_binding=None)
        elif case == "id":
            altered = replace(resumed, primary_binding=replace(primary, capability_id="other"))
        elif case == "revision":
            altered = replace(resumed, primary_binding=replace(primary, descriptor_revision=2))
        else:
            requirement = replace(primary.requirement, allow_degraded=True)
            altered = replace(
                resumed,
                command=replace(resumed.command, required_capabilities=(requirement,)),
                primary_binding=replace(primary, requirement=requirement),
            )
        with pytest.raises(ValueError, match="再開"):
            replace(scope, bindings=(replace(binding, resumed_invocation=altered),))
        assert len(provider.calls) == 1
    finally:
        provider.release.set()
        await asyncio.gather(original, return_exceptions=True)
