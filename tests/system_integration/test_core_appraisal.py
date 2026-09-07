"""本体の所有者の更新と実際のBrain実行を使い、評価接続を検証する。"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, cast

import pytest

from app.composition.appraisal import (
    AppraisalBrainModulePort,
    AppraisalBrainWorkPayload,
    CoreAppraisalBinding,
)
from app.domain.appraisal import AppraisalStateCommit, InternalStateReducer
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
    BrainWorkEnvelope,
    BrainWorkPriority,
    BrainWorkStatus,
)
from app.domain.contracts import EventEnvelope, RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.executive import GoalTransitionOperation
from app.domain.goals import GoalCommitmentStore
from app.domain.input_meaning import StructuredInputMeaning
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.runtime.kernel import CancellationToken, FakeRuntimeClock
from tests.domain.appraisal.test_appraisal_paths import NOW, event, meaning, policy, result, state
from tests.domain.brain_integration.test_runtime import FakePort
from tests.domain.brain_integration.test_runtime import policy as runtime_policy
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.system_integration.test_input_reference_context import binding


class Port:
    def __init__(self, *, waiting: bool = False) -> None:
        self.requests: list[LLMRoleRequest] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not waiting:
            self.release.set()

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return replace(
            result(request), started_at=request.created_at, completed_at=request.created_at
        )


@dataclass
class Setup:
    goals: GoalCommitmentStore
    owner: InternalStateReducer
    port: Port
    clock: FakeRuntimeClock
    connection: CoreAppraisalBinding
    event: EventEnvelope
    meaning: StructuredInputMeaning

    async def appraise(self, request_id: str = "request") -> AppraisalStateCommit:
        return await self.connection.appraise(
            self.event,
            self.meaning,
            request_id=request_id,
            cancellation=CancellationToken(),
        )


def setup(port: Port | None = None) -> Setup:
    goals = GoalCommitmentStore()
    owner = InternalStateReducer(replace(state(), source_context_revision=0))
    provided = Port() if port is None else port
    clock = FakeRuntimeClock(NOW + timedelta(seconds=3))
    connection = CoreAppraisalBinding(binding(goals), owner, provided, policy(), clock)
    return Setup(
        goals,
        owner,
        provided,
        clock,
        connection,
        replace(event(), revisions=RevisionVector(1)),
        replace(meaning(), source_context_revision=1),
    )


@pytest.mark.asyncio
async def test_current_owner_state_and_new_context_reach_atomic_commit() -> None:
    value = setup()
    initial = value.owner.snapshot()
    first = await value.appraise()
    request = cast(Mapping[str, Any], value.port.requests[0].input.value)
    assert request["state"] == freeze_json(initial.to_dict())
    assert request["meaning"] == freeze_json(value.meaning.to_dict())
    assert initial.source_context_revision == 0
    assert first.internal_state is value.owner.snapshot()
    assert first.appraisal_facts.source_context_revision == 1
    assert first.appraisal_facts.internal_state_revision == first.internal_state.revision
    assert value.connection.current_commit() is first
    apply_goal(value.goals, GoalTransitionOperation.CREATE, 0)
    assert value.connection.current_commit() is None
    assert value.connection.latest_commit() is first
    value.event = replace(value.event, revisions=RevisionVector(2))
    value.meaning = replace(value.meaning, source_context_revision=2)
    second = await value.appraise("second")
    assert second.candidate.base_state_revision == first.internal_state.revision
    assert second.appraisal_facts.revision == first.appraisal_facts.revision + 1
    assert value.connection.current_commit() is second
    request = cast(Mapping[str, Any], value.port.requests[-1].input.value)
    assert request["context"]["context_refs"] == ("goal-1",)


@pytest.mark.asyncio
async def test_goal_change_during_response_rejects_commit() -> None:
    value = setup(Port(waiting=True))
    original = value.owner.snapshot()
    task = asyncio.create_task(value.appraise())
    await asyncio.wait_for(value.port.started.wait(), 1)
    apply_goal(value.goals, GoalTransitionOperation.CREATE, 0)
    value.port.release.set()
    with pytest.raises(ValueError, match="stale source"):
        await task
    assert value.owner.snapshot() is original
    assert value.connection.latest_commit() is None


@pytest.mark.asyncio
async def test_competing_evaluations_commit_only_one_state_and_facts_pair() -> None:
    value = setup(Port(waiting=True))
    tasks = [asyncio.create_task(value.appraise(str(index))) for index in range(2)]
    while len(value.port.requests) < 2:
        await asyncio.sleep(0)
    value.port.release.set()
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    committed = [item for item in outcomes if isinstance(item, AppraisalStateCommit)]
    assert len(committed) == 1
    assert sum(isinstance(item, ValueError) for item in outcomes) == 1
    assert value.connection.current_commit() is committed[0]
    assert committed[0].appraisal_facts.revision == 1
    assert value.owner.snapshot().revision == 4


@pytest.mark.asyncio
async def test_external_state_commit_invalidates_pending_result_and_retained_pair() -> None:
    value = setup()
    first = await value.appraise()
    value.port.release.clear()
    value.port.started.clear()
    task = asyncio.create_task(value.appraise("waiting"))
    await asyncio.wait_for(value.port.started.wait(), 1)
    competing = replace(first.candidate, base_state_revision=first.internal_state.revision)
    changed = value.owner.commit(
        competing,
        current_source_context_revision=1,
        committed_at=value.clock.now(),
    )
    value.port.release.set()
    with pytest.raises(ValueError, match="stale state"):
        await task
    assert value.owner.snapshot() is changed
    assert value.connection.current_commit() is None
    assert value.connection.latest_commit() is first


@pytest.mark.asyncio
async def test_cancelled_provider_result_is_reaped_without_commit_even_on_recancellation() -> None:
    caught, finish = asyncio.Event(), asyncio.Event()

    class SuppressingPort(Port):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            try:
                return await super().invoke(request)
            except asyncio.CancelledError:
                caught.set()
                await finish.wait()
                return replace(
                    result(request), started_at=request.created_at, completed_at=request.created_at
                )

    value = setup(SuppressingPort(waiting=True))
    before = asyncio.all_tasks()
    initial = value.owner.snapshot()
    task = asyncio.create_task(value.appraise())
    await asyncio.wait_for(value.port.started.wait(), 1)
    task.cancel()
    await asyncio.wait_for(caught.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert value.owner.snapshot() is initial
    assert value.connection.latest_commit() is None
    assert not (asyncio.all_tasks() - before)


@pytest.mark.asyncio
async def test_mismatched_meaning_and_stale_input_do_not_call_or_commit() -> None:
    value = setup()
    original = value.owner.snapshot()
    value.meaning = replace(value.meaning, source_event_id="wrong")
    with pytest.raises(ValueError, match="meaning source"):
        await value.appraise()
    assert not value.port.requests
    assert value.owner.snapshot() is original
    assert value.connection.latest_commit() is None
    value.meaning = replace(value.meaning, source_event_id=value.event.event_id)
    apply_goal(value.goals, GoalTransitionOperation.CREATE, 0)
    with pytest.raises(ValueError, match="現在の参照文脈"):
        await value.appraise()
    assert not value.port.requests


def brain_work(value: Setup) -> BrainIntegrationWork:
    return BrainIntegrationWork(
        "appraisal",
        BrainIntegrationModule.APPRAISAL,
        BrainIntegrationLane.COGNITIVE_NORMAL,
        BrainWorkEnvelope(
            value.event.trace_id,
            "trigger",
            (value.event.event_id,),
            1,
            None,
            None,
            BrainWorkPriority.NORMAL,
            value.clock.now(),
        ),
        AppraisalBrainWorkPayload(value.event, value.meaning, "brain-request"),
    )


@pytest.mark.asyncio
async def test_brain_keeps_foreground_running_and_returns_actual_commit() -> None:
    value = setup(Port(waiting=True))
    runtime = BrainIntegrationRuntime(value.clock, runtime_policy())
    runtime.register_module(
        BrainIntegrationModule.APPRAISAL, AppraisalBrainModulePort(value.connection)
    )
    runtime.register_module(BrainIntegrationModule.INPUT_MEANING, FakePort("別の処理"))
    await runtime.start()
    try:
        item = brain_work(value)
        assert runtime.submit(item).accepted
        await asyncio.wait_for(value.port.started.wait(), 1)
        foreground = replace(
            item,
            work_id="foreground",
            module=BrainIntegrationModule.INPUT_MEANING,
            lane=BrainIntegrationLane.FOREGROUND_INTERACTION,
        )
        assert runtime.submit(foreground).accepted
        outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
        assert outcome.work_id == "foreground"
        assert outcome.result == "別の処理"
        assert value.connection.latest_commit() is None
        value.port.release.set()
        outcome = await asyncio.wait_for(runtime.next_outcome(), 1)
        assert outcome.status is BrainWorkStatus.COMPLETED
        assert outcome.result is value.connection.current_commit()
    finally:
        value.port.release.set()
        await runtime.stop()


@pytest.mark.asyncio
async def test_brain_stop_reaps_evaluation_without_state_commit() -> None:
    value = setup(Port(waiting=True))
    runtime = BrainIntegrationRuntime(value.clock, runtime_policy())
    runtime.register_module(
        BrainIntegrationModule.APPRAISAL, AppraisalBrainModulePort(value.connection)
    )
    before = asyncio.all_tasks()
    await runtime.start()
    assert runtime.submit(brain_work(value)).accepted
    await asyncio.wait_for(value.port.started.wait(), 1)
    await runtime.stop()
    assert value.connection.latest_commit() is None
    assert value.owner.snapshot().revision == 3
    assert not (asyncio.all_tasks() - before)


@pytest.mark.asyncio
async def test_live_reference_failure_after_response_does_not_commit() -> None:
    value = setup(Port(waiting=True))
    value.connection = CoreAppraisalBinding(
        binding(value.goals, max_entries=1),
        value.owner,
        value.port,
        policy(),
        value.clock,
    )
    initial = value.owner.snapshot()
    task = asyncio.create_task(value.appraise())
    await asyncio.wait_for(value.port.started.wait(), 1)
    apply_goal(value.goals, GoalTransitionOperation.CREATE, 0)
    apply_goal(value.goals, GoalTransitionOperation.CREATE, 1, goal_id="goal-2")
    value.port.release.set()
    with pytest.raises(ValueError, match="exceeds max_entries"):
        await task
    assert value.owner.snapshot() is initial
    assert value.connection.latest_commit() is None


@pytest.mark.asyncio
async def test_cancellation_token_prevents_commit_after_response() -> None:
    from app.runtime.kernel.contracts import CancellationRecord

    value = setup(Port(waiting=True))
    token = CancellationToken()
    task = asyncio.create_task(
        value.connection.appraise(
            value.event,
            value.meaning,
            request_id="token",
            cancellation=token,
        )
    )
    await asyncio.wait_for(value.port.started.wait(), 1)
    token.cancel(CancellationRecord("token", "停止要求", value.clock.now()))
    value.port.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert value.owner.snapshot().revision == 3
    assert value.connection.latest_commit() is None
    with pytest.raises(asyncio.CancelledError):
        await value.connection.appraise(
            value.event,
            value.meaning,
            request_id="already-cancelled",
            cancellation=token,
        )
    assert len(value.port.requests) == 1


@pytest.mark.parametrize("field", ["trace_id", "source_event_ids", "source_context_revision"])
def test_module_rejects_mismatched_brain_envelope(field: str) -> None:
    value = setup()
    item = brain_work(value)
    invalid = {
        "trace_id": replace(item.envelope, trace_id="wrong"),
        "source_event_ids": replace(item.envelope, source_event_ids=("wrong",)),
        "source_context_revision": replace(item.envelope, source_context_revision=2),
    }
    item = replace(item, envelope=invalid[field])
    with pytest.raises(ValueError, match="一致しません"):
        AppraisalBrainModulePort(value.connection).is_fresh(item)
    assert not value.port.requests


@pytest.mark.asyncio
async def test_context_change_between_candidate_acceptance_and_commit_is_rechecked() -> None:
    value = setup()

    class ScheduledChangePort(Port):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            response = await super().invoke(request)
            # 候補の同期検査後、親処理が確定を再開する前に実所有者を更新する。
            asyncio.get_running_loop().call_soon(
                apply_goal,
                value.goals,
                GoalTransitionOperation.CREATE,
                0,
            )
            return response

    value.connection = CoreAppraisalBinding(
        binding(value.goals),
        value.owner,
        ScheduledChangePort(),
        policy(),
        value.clock,
    )
    initial = value.owner.snapshot()
    with pytest.raises(ValueError, match="stale for source context"):
        await value.appraise()
    assert value.owner.snapshot() is initial
    assert value.connection.latest_commit() is None
