"""本番認知・背景Reflectionの非直列性と終端回収を外部境界で同期検証する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from app import bootstrap
from app.composition.reflection import CoreReflectionConfiguration
from app.domain.activity_execution import ExecutionAdapterReport
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainWorkAdmissionStatus,
    BrainWorkStatus,
)
from app.domain.contracts import ExecutionStatus
from app.domain.executive import GoalTransitionOperation
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.domain.memory_reflection import ReflectionAcceptancePolicy
from app.infrastructure.persistence import PostgresEndpoint
from tests.domain.activity_execution.test_activity_execution import NOW, invocation, preflight
from tests.domain.brain_integration.test_runtime import envelope, work
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.domain.memory_reflection.test_llm_roles import RolePort, role_policy
from tests.infrastructure.postgresql.test_persistent_boot import boot_config  # noqa: F401
from tests.infrastructure.postgresql.test_runtime import runtime
from tests.runtime.test_lifecycle import retry_policy
from tests.system_integration.test_core_cognition import Port, admission, application
from tests.system_integration.test_core_cognition_hardening import configuration


async def outcome(app: Any) -> Any:
    return await asyncio.wait_for(app.brain.next_outcome(), 3)


def assert_reaped(app: Any) -> None:
    diagnostics = app.brain._runtime.diagnostics()
    assert diagnostics.owned_task_count == 0
    assert all(lane.in_flight == lane.queue_depth == 0 for lane in diagnostics.lanes)
    assert app.brain._pump_task.done()
    assert not app.brain._pending_runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "supersede", "goal_revision"])
async def test_slow_appraisal_trace_local_terminal_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    app, port = application(monkeypatch)
    gates = {key: asyncio.Event() for key in ("trace-A", "trace-B")}
    entered = {key: asyncio.Event() for key in gates}
    exited = {key: asyncio.Event() for key in gates}
    requests: dict[str, LLMRoleRequest] = {}
    original = port.invoke

    async def controlled(request: LLMRoleRequest) -> LLMRoleResult:
        if request.role_id == "subjective_appraisal":
            requests[request.trace_id] = request
            entered[request.trace_id].set()
            try:
                await gates[request.trace_id].wait()
                return await original(request)
            finally:
                exited[request.trace_id].set()
        return await original(request)

    monkeypatch.setattr(port, "invoke", controlled)
    await app.start()
    try:
        assert app.cognition.submit_input(
            admission(app, event_id="event-A", trace_id="trace-A")
        ).accepted
        await asyncio.wait_for(entered["trace-A"].wait(), 3)
        first = await outcome(app)
        assert first.module is BrainIntegrationModule.INPUT_MEANING
        assert first.status is BrainWorkStatus.COMPLETED
        assert app.cognition.submit_input(
            admission(app, event_id="event-B", trace_id="trace-B")
        ).accepted
        await asyncio.wait_for(entered["trace-B"].wait(), 3)
        second = await outcome(app)
        assert second.trace_id == "trace-B"
        assert second.module is BrainIntegrationModule.INPUT_MEANING
        assert second.status is BrainWorkStatus.COMPLETED
        assert not gates["trace-A"].is_set() and not exited["trace-A"].is_set()
        for key in gates:
            trace = app.brain.trace(key)
            event = key.replace("trace", "event")
            assert trace.root_trigger_id == event
            assert trace.source_event_ids == (event,)
            assert requests[key].trace_id == key
            assert event in str(requests[key].input.value)
            other = "event-B" if key == "trace-A" else "event-A"
            assert other not in str(requests[key].input.value)
            appraisal_work = next(
                item.work
                for item in app.brain._tracked.values()
                if item.work.envelope.trace_id == key
                and item.work.module is BrainIntegrationModule.APPRAISAL
            )
            assert (
                requests[key].revisions.source_context_revision
                == appraisal_work.envelope.source_context_revision
            )
            # LLM要求は元イベントのrevision、workは受付時のOwner参照を保持する。
            assert requests[key].revisions == appraisal_work.payload.event.revisions
            assert (
                appraisal_work.envelope.goal_revision
                == app.input_context.snapshot().goals.goal_revision
            )
            assert appraisal_work.envelope.attention_revision is None
        if mode == "goal_revision":
            before = app.goals.snapshot()
            apply_goal(app.goals, GoalTransitionOperation.CREATE, 0)
            assert app.goals.snapshot() != before
            gates["trace-A"].set()
            gates["trace-B"].set()
            rejected = [await outcome(app) for _ in range(2)]
            assert all(o.status is BrainWorkStatus.FAILED for o in rejected)
            assert all(o.module is BrainIntegrationModule.APPRAISAL for o in rejected)
            assert app.cognition.appraisal.current_commit() is None
            assert not any(r.role_id == "executive_deliberation" for r in port.requests)
        else:
            assert (
                app.cognition.cancel_trace("trace-A", "対象だけ取消", supersede=mode == "supersede")
                == 1
            )
            rejected = await outcome(app)
            assert rejected.trace_id == "trace-A"
            assert rejected.status is (
                BrainWorkStatus.SUPERSEDED if mode == "supersede" else BrainWorkStatus.CANCELLED
            )
            await asyncio.wait_for(exited["trace-A"].wait(), 3)
            assert not exited["trace-B"].is_set()
            gates["trace-B"].set()
            completed = [await outcome(app) for _ in range(2)]
            assert all(
                o.trace_id == "trace-B" and o.status is BrainWorkStatus.COMPLETED for o in completed
            )
            decision = completed[-1]
            assert decision.module is BrainIntegrationModule.EXECUTIVE
            assert decision.result.candidate.source_event_ids == ("event-B",)
            decision_envelope = app.brain._tracked[decision.work_id].work.envelope
            request = next(r for r in port.requests if r.role_id == "executive_deliberation")
            assert decision_envelope.root_trigger_id == "event-B"
            assert decision.result.candidate.trigger_id == decision_envelope.trigger_id
            assert (
                request.revisions.source_context_revision
                == decision_envelope.source_context_revision
            )
            assert request.revisions.goal_revision == decision_envelope.goal_revision
            assert request.revisions.attention_revision == decision_envelope.attention_revision
            assert all(
                r.trace_id != "trace-A"
                for r in port.requests
                if r.role_id == "executive_deliberation"
            )
        assert not app.brain.trace("trace-A").activity_ids
        assert not app.brain.trace("trace-A").speech_candidate_ids
    finally:
        for gate in gates.values():
            gate.set()
        await app.stop()
    assert_reaped(app)


@pytest.mark.asyncio
async def test_stop_caller_cancel_still_reaps_provider_and_unique_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = asyncio.all_tasks()
    app, port = application(monkeypatch)
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = port.invoke

    async def controlled(request: LLMRoleRequest) -> LLMRoleResult:
        if request.role_id == "subjective_appraisal":
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup.set()
                await release.wait()
                raise
        return await original(request)

    monkeypatch.setattr(port, "invoke", controlled)
    await app.start()
    try:
        accepted = app.cognition.submit_input(admission(app, internal=True))
        await asyncio.wait_for(entered.wait(), 3)
        stopping = asyncio.create_task(app.stop())
        await asyncio.wait_for(cleanup.wait(), 3)
        stopping.cancel()
        assert not app.brain._pump_task.done()
        with pytest.raises(RuntimeError, match="受付"):
            app.cognition.submit_input(
                admission(app, internal=True, event_id="late", trace_id="late")
            )
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stopping, 3)
        terminal = await outcome(app)
        assert terminal.work_id == accepted.work_id
        assert terminal.status is BrainWorkStatus.CANCELLED
        await app.stop()
        assert app.brain._outcomes.empty()
        assert not app.brain.cancel(accepted.work_id, "回収済み")
    finally:
        release.set()
        await app.stop()
    assert_reaped(app)
    assert not (asyncio.all_tasks() - baseline)


def complete_activity(app: Any, index: int) -> Any:
    identity = f"command-{index}"
    item = invocation(identity)
    dispatch = f"dispatch-{index}"
    app.activities.admit(item, preflight())
    app.activities.start(identity, preflight(), NOW + timedelta(seconds=1), dispatch)
    record = app.activities.apply_report(
        ExecutionAdapterReport(
            identity,
            item.invocation_id,
            dispatch,
            ExecutionStatus.COMPLETED,
            NOW + timedelta(seconds=2),
            {"code": "completed"},
        )
    ).record
    parent = work(
        f"activity-{index}",
        BrainIntegrationModule.ACTIVITY_EXECUTION,
        BrainIntegrationLane.COGNITIVE_NORMAL,
        work_envelope=envelope(trace_id=f"background-{index}", trigger_id=f"root-{index}"),
    )
    app.cognition.reflection.observe_activity(parent, record)
    return app.cognition.reflection.latest_admission


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_pending", [False, True])
async def test_real_activity_reflection_burst_keeps_foreground_and_bounded_cleanup(
    endpoint: PostgresEndpoint,
    boot_config: Path,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    stop_pending: bool,
) -> None:
    baseline = asyncio.all_tasks()
    data = yaml.safe_load(boot_config.read_text())
    for lane in data["integration"]["lane_policies"]:
        if lane["lane_id"] == "background_reflection":
            lane["queue_capacity"] = 1
    boot_config.write_text(yaml.safe_dump(data))
    port = Port()
    reflection_entered, reflection_release = asyncio.Event(), asyncio.Event()
    reflected: list[LLMRoleRequest] = []
    original = port.invoke

    async def controlled(request: LLMRoleRequest) -> LLMRoleResult:
        if request.role_id == "memory_reflection":
            reflected.append(request)
            reflection_entered.set()
            await reflection_release.wait()
            value = await RolePort({"proposals": []}).invoke(request)
            return replace(value, started_at=request.created_at, completed_at=request.created_at)
        return await original(request)

    monkeypatch.setattr(port, "invoke", controlled)
    monkeypatch.setattr(bootstrap, "create_openai_port_from_environment", lambda roles: port)
    persistence = runtime(endpoint)
    app = await bootstrap.build_persistent_core(
        boot_config,
        persistence=persistence,
        retry_policy=retry_policy("db", retry_enabled=False),
        runtime_epoch="brain-f",
        max_pending_memory=4,
        cognition=replace(
            configuration(),
            reflection=CoreReflectionConfiguration(
                role_policy(),
                ReflectionAcceptancePolicy("accept", 1),
                8,
            ),
        ),
    )
    await app.start()
    try:
        assert app.cognition is not None and app.cognition.reflection is not None
        first = complete_activity(app, 1)
        assert first.accepted
        await asyncio.wait_for(reflection_entered.wait(), 3)
        queued = complete_activity(app, 2)
        assert queued.accepted
        rejected = complete_activity(app, 3)
        assert app.cognition.reflection.last_error is None, repr(
            app.cognition.reflection.last_error
        )
        assert rejected.status is BrainWorkAdmissionStatus.REJECTED
        terminal = await outcome(app)
        assert terminal.work_id == rejected.work_id and terminal.status is BrainWorkStatus.REJECTED
        assert app.cognition is not None
        assert app.cognition.submit_input(
            admission(app, event_id="front", trace_id="front")
        ).accepted
        foreground = [await outcome(app) for _ in range(3)]
        assert all(
            o.trace_id == "front" and o.status is BrainWorkStatus.COMPLETED for o in foreground
        )
        assert foreground[-1].module is BrainIntegrationModule.EXECUTIVE
        assert foreground[-1].result.candidate.source_event_ids == ("front",)
        assert not reflection_release.is_set()
        assert len(reflected) == 1 and reflected[0].trace_id == "background-1"
        assert "command-1" in str(reflected[0].input.value)
        assert app.brain.trace("front").root_trigger_id == "front"
        if stop_pending:
            await app.stop()
        else:
            reflection_release.set()
        background = [await outcome(app) for _ in range(2)]
        assert {o.work_id for o in background} == {first.work_id, queued.work_id}
        assert all(
            o.status is (BrainWorkStatus.CANCELLED if stop_pending else BrainWorkStatus.COMPLETED)
            for o in background
        )
        if not stop_pending:
            assert {r.trace_id for r in reflected} == {"background-1", "background-2"}
    finally:
        reflection_release.set()
        await app.stop()
    assert_reaped(app)
    assert app.cognition is not None and app.cognition.reflection is not None
    assert not app.cognition.reflection._pending
    assert app.memory is not None and app.memory.pending_count == 0
    assert persistence.pending_task_count == 0
    assert app.brain._outcomes.empty()
    assert not (asyncio.all_tasks() - baseline)
