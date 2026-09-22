"""実際の所有者の更新を入力意味の採用直前に検出する。"""

import asyncio
from dataclasses import replace
from typing import cast

import pytest

from app import bootstrap
from app.bootstrap import InputMeaningBrainWorkPayload
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import RevisionVector
from app.domain.contracts.snapshots import SnapshotIncoherentError, SnapshotInvariantError
from app.domain.executive import GoalTransitionOperation
from app.domain.goals import GoalCommitmentSnapshot, GoalCommitmentStore
from app.domain.input_meaning import InputMeaningInterpretationResult, InputMeaningInterpreter
from app.domain.llm import LLMFailureCode, LLMRoleRequest, LLMRoleResult
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.domain.input_meaning.test_input_meaning import NOW, event, policy
from tests.domain.plan_execution.test_progression import WaitingProvider, runner, setup
from tests.system_integration.test_early_boot import SuccessfulPort, work


def binding(
    store: GoalCommitmentStore, *, max_entries: int = 32
) -> CoreInputReferenceContextBinding:
    return CoreInputReferenceContextBinding(
        store,
        ActivityExecutionAuthority(),
        policy(),
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        max_entries=max_entries,
    )


def test_goal_references_keep_native_revision_and_projection_generation_separate() -> None:
    value = setup()
    context = binding(value.goals)
    first = context.snapshot()
    assert context.snapshot() is first
    assert first.goals.goal_revision == value.goals.snapshot().revision
    assert first.context.source_context_revision == 1
    assert first.context.entries[0].subject_ref == "goal-1"
    assert first.context.entries[0].revision == 1
    assert len(first.context.entries) == 1
    assert first.freshness.acceptance_policy_revision == policy().acceptance.policy_revision


@pytest.mark.asyncio
async def test_goal_change_during_llm_wait_rejects_old_meaning() -> None:
    store = GoalCommitmentStore()
    context = binding(store)
    first = context.snapshot()
    started, release = asyncio.Event(), asyncio.Event()

    class SlowPort(SuccessfulPort):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            started.set()
            await release.wait()
            return await super().invoke(request)

    interpreter = InputMeaningInterpreter(SlowPort(), context, policy())
    observed = event()
    observed = replace(
        observed,
        envelope=replace(
            observed.envelope, revisions=RevisionVector(first.context.source_context_revision)
        ),
    )
    task = asyncio.create_task(
        interpreter.interpret(
            observed, first.context, request_id="r", trace_id="trace-1", created_at=NOW
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 1)
        apply_goal(store, GoalTransitionOperation.CREATE, 0)
        release.set()
        result = await task
        assert result.meaning is None
        assert result.boundary_failure is not None
        assert result.boundary_failure.code is LLMFailureCode.STALE
        assert context.snapshot().context.source_context_revision == 2
        assert first.context.entries == ()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_activity_result_refreshes_projection_without_changing_goal() -> None:
    value = setup()
    context = CoreInputReferenceContextBinding(
        value.goals, value.activity, policy(), V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
    )
    provider = WaitingProvider(value)
    task = asyncio.create_task(runner(value, provider).advance(value.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        command_id = provider.calls[0].command.command_id
        context.set_activity_references((command_id,))
        first = context.snapshot()
        assert first.activities[0] == value.activity.snapshot(command_id)
        provider.release.set()
        await task
        second = context.snapshot()
        assert second.context.source_context_revision == first.context.source_context_revision + 1
        assert second.goals == first.goals
        assert second.activities[0].terminal
        assert second.activities[0].record_revision > first.activities[0].record_revision
        context.set_activity_references(())
        assert context.snapshot().activities == ()
    finally:
        provider.release.set()
        await asyncio.gather(task, return_exceptions=True)


def test_unknown_duplicate_and_excess_activity_references_are_rejected() -> None:
    context = binding(GoalCommitmentStore(), max_entries=1)
    first = context.snapshot()
    for values in (("unknown",), ("same", "same"), ("one", "two")):
        with pytest.raises(ValueError):
            context.set_activity_references(values)
    assert context.snapshot() is first


def test_reference_overflow_does_not_return_old_context_as_current() -> None:
    store = GoalCommitmentStore()
    context = binding(store, max_entries=1)
    first = context.snapshot()
    apply_goal(store, GoalTransitionOperation.CREATE, 0)
    apply_goal(store, GoalTransitionOperation.CREATE, 1, goal_id="goal-2")
    with pytest.raises(ValueError, match="exceeds max_entries"):
        context.snapshot()
    assert first.context.entries == ()


@pytest.mark.parametrize("failure", ["unstable", "same_revision", "regression"])
def test_bad_owner_generations_do_not_replace_published_projection(failure: str) -> None:
    real = setup().goals
    original = real.snapshot()

    class Source:
        mode = "good"
        calls = 0

        def snapshot(self) -> GoalCommitmentSnapshot:
            self.calls += 1
            if self.mode == "unstable":
                return replace(original, revision=original.revision + self.calls)
            if self.mode == "same_revision":
                return replace(original, goals=(replace(original.goals[0], priority=99),))
            if self.mode == "regression":
                return GoalCommitmentStore().snapshot()
            return original

    source = Source()
    context = CoreInputReferenceContextBinding(
        source, ActivityExecutionAuthority(), policy(), V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
    )
    first = context.snapshot()
    source.mode = failure
    with pytest.raises((SnapshotIncoherentError, SnapshotInvariantError)):
        context.snapshot()
    source.mode = "good"
    assert context.snapshot() is first


@pytest.mark.asyncio
async def test_minimum_boot_uses_real_current_context_and_commits_meaning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrap, "create_openai_port_from_environment", lambda _: SuccessfulPort()
    )
    baseline = asyncio.all_tasks()
    app = bootstrap.build_minimum_core()
    snapshot = app.input_context.snapshot()
    value = work()
    payload = cast(InputMeaningBrainWorkPayload, value.payload)
    captured = replace(
        payload.event,
        envelope=replace(
            payload.event.envelope,
            revisions=RevisionVector(snapshot.context.source_context_revision),
        ),
    )
    value = replace(
        value,
        envelope=replace(
            value.envelope, source_context_revision=snapshot.context.source_context_revision
        ),
        payload=replace(payload, event=captured, reference_context=snapshot.context),
    )
    await app.start()
    try:
        assert app.brain.submit(value).accepted
        outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert isinstance(outcome.result, InputMeaningInterpretationResult)
        assert outcome.result.meaning is not None
        assert outcome.result.boundary_failure is None
        assert app.goals.snapshot().goals == ()
    finally:
        await app.stop()
    assert not (asyncio.all_tasks() - baseline)
