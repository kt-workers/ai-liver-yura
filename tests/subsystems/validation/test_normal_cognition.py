"""本番compositionを使い、通常認知adapterの証拠と資源回収を確認する。"""

import asyncio
from dataclasses import replace
from typing import Any, cast

import pytest

from app.bootstrap import MinimumCoreApplication
from app.domain.executive import GoalTransitionOperation
from app.subsystems.validation.body import _project
from app.subsystems.validation.cognition import NormalCognitionLabCase, normal_cognition_target
from app.subsystems.validation.contracts import Gate, LabMode, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec
from tests.system_integration.test_core_cognition import admission, application


async def wait_for_ports(ports: list[Any]) -> None:
    """呼出側の有限期限内でfactoryの起動を待つ。"""
    while not ports:
        await asyncio.sleep(0)


def setup(monkeypatch: pytest.MonkeyPatch, *, internal: bool = False, slow: bool = False) -> Any:
    app, port = application(monkeypatch)
    event = admission(app, internal=internal)
    fixture = replace(FIXTURE, typed_inputs=_project(event))
    created: list[MinimumCoreApplication] = []
    ports = []

    def factory() -> MinimumCoreApplication:
        current, provider = (app, port) if not created else application(monkeypatch)
        if slow:
            provider.release.clear()
        created.append(current)
        ports.append(provider)
        return cast(MinimumCoreApplication, current)

    target = normal_cognition_target(
        (NormalCognitionLabCase(fixture, event),), factory, PROVENANCE, "1", ()
    )
    policy = replace(POLICY, timeout_seconds=3, max_intervals=100)
    runner = ValidationRunner((target,), policy)
    request = replace(spec(), mode=LabMode.INTEGRATED, target_module="normal_cognition")
    return runner, request, fixture, created, ports, target


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [False, True])
async def test_production_chain_and_repeated_fresh_owner(
    monkeypatch: pytest.MonkeyPatch, internal: bool
) -> None:
    runner, request, fixture, apps, ports, _ = setup(monkeypatch, internal=internal)
    result = await runner.run(replace(request, repeat_count=2), fixture)
    assert result.status is RunStatus.COMPLETED, result
    assert result.machine_gate is Gate.PASS
    assert len(apps) == 2 and apps[0] is not apps[1]
    assert apps[0].brain is not apps[1].brain
    assert apps[0].cognition is not apps[1].cognition
    for observation in result.stage_results:
        value = observation.typed_outputs
        assert value["trace"]["root_trigger_id"] == "event-1"
        assert value["trace"]["source_event_ids"] == ("event-1",)
        modules = [o["module"] for o in value["outcomes"]]
        assert modules == (
            ["appraisal", "executive"] if internal else ["input_meaning", "appraisal", "executive"]
        )
        assert all(
            i["source_context_revision"]
            == fixture.typed_inputs["event"]["envelope"]["revisions"]["source_context_revision"]
            for i in value["trace"]["intervals"]
        )
        assert value["outcomes"][-1]["result"]["candidate"]["source_event_ids"] == ("event-1",)
    assert runner.pending_count == 0
    encoded = result.export_json(1_000_000)
    assert "INTEGRATED" in encoded and "SYSTEM_SLICE" not in encoded
    assert "Authorization" not in encoded and "raw_prompt" not in encoded
    assert all(len(p.requests) == (2 if internal else 3) for p in ports)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["fixture", "revision", "mode", "contract", "provider"])
async def test_mismatch_never_builds_application(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    runner, request, fixture, apps, _, _ = setup(monkeypatch)
    if mutation == "fixture":
        fixture = replace(fixture, typed_inputs=None)
    elif mutation == "revision":
        request = replace(request, fixture_revision="different")
    elif mutation == "mode":
        request = replace(request, mode=LabMode.SYSTEM_SLICE)
    elif mutation == "contract":
        request = replace(request, target_contract_revision="different")
    else:
        request = replace(request, provider_policy_refs=("different",))
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert apps == [] and runner.pending_count == 0


@pytest.mark.asyncio
async def test_real_goal_update_rejects_stale_appraisal(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, request, fixture, apps, ports, _ = setup(monkeypatch, internal=True, slow=True)
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(wait_for_ports(ports), 2)
    await asyncio.wait_for(ports[0].entered.wait(), 2)
    apply_goal(apps[0].goals, GoalTransitionOperation.CREATE, 0)
    ports[0].release.set()
    result = await task
    assert result.status is RunStatus.PRODUCT_FAILED
    assert result.stage_results[0].typed_outputs["outcomes"][0]["status"] == "failed"
    assert apps[0].cognition.appraisal.current_commit() is None
    assert len(ports[0].requests) == 1 and runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "timeout", "close", "caller"])
async def test_cancel_and_timeout_reap_owned_application(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    runner, request, fixture, apps, ports, target = setup(monkeypatch, internal=True, slow=True)
    if operation == "timeout":
        runner = ValidationRunner((target,), replace(POLICY, timeout_seconds=0.1))
    before = asyncio.all_tasks()
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(wait_for_ports(ports), 2)
    await asyncio.wait_for(ports[0].entered.wait(), 2)
    if operation == "cancel":
        await runner.cancel(request.run_id)
    elif operation == "close":
        await runner.close()
    elif operation == "caller":
        task.cancel()
    try:
        result = await task
    except asyncio.CancelledError:
        result = runner.result(request.run_id)
    assert result.status is (RunStatus.TIMED_OUT if operation == "timeout" else RunStatus.CANCELLED)
    assert runner.pending_count == 0
    assert apps[0].cognition.appraisal.current_commit() is None
    assert len(ports[0].requests) == 1
    assert not (asyncio.all_tasks() - before - {asyncio.current_task()})


@pytest.mark.asyncio
@pytest.mark.parametrize("supersede", [False, True])
async def test_production_cancel_status_preserved(
    monkeypatch: pytest.MonkeyPatch, supersede: bool
) -> None:
    runner, request, fixture, apps, ports, _ = setup(monkeypatch, internal=True, slow=True)
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(wait_for_ports(ports), 2)
    await asyncio.wait_for(ports[0].entered.wait(), 2)
    assert apps[0].cognition.cancel_trace("trace-1", "検証取消", supersede=supersede) == 1
    result = await task
    assert result.status is (RunStatus.PRODUCT_FAILED if supersede else RunStatus.CANCELLED)
    assert result.stage_results[0].typed_outputs["outcomes"][0]["status"] == (
        "superseded" if supersede else "cancelled"
    )
    assert len(ports[0].requests) == 1 and runner.pending_count == 0


@pytest.mark.asyncio
async def test_provider_exception_is_not_exported(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, request, fixture, apps, ports, _ = setup(monkeypatch, internal=True, slow=True)
    from tests.system_integration.test_core_cognition import Port

    async def fail(self: Any, request: Any) -> Any:
        raise RuntimeError("Authorization: private-provider-secret")

    monkeypatch.setattr(Port, "invoke", fail)
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert result.stage_results[0].typed_outputs["outcomes"][0]["status"] == "failed"
    assert "private-provider-secret" not in result.export_json(1_000_000)
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_typed_meaning_failure_does_not_wait_for_next_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.llm.production import UnavailableLLMRolePort
    from tests.system_integration.test_core_cognition import Port

    async def unavailable(self: Any, request: Any) -> Any:
        return await UnavailableLLMRolePort(()).invoke(request)

    monkeypatch.setattr(Port, "invoke", unavailable)
    runner, request, fixture, _, _, _ = setup(monkeypatch)
    result = await asyncio.wait_for(runner.run(request, fixture), 1)
    assert result.status is RunStatus.PROVIDER_FAILED
    assert len(result.stage_results[0].typed_outputs["outcomes"]) == 1
    assert result.stage_results[0].typed_outputs["outcomes"][0]["status"] == "completed"
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_repeated_caller_cancel_waits_for_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, request, fixture, apps, ports, _ = setup(monkeypatch, internal=True, slow=True)
    original = MinimumCoreApplication.stop
    entered, release = asyncio.Event(), asyncio.Event()

    async def stop(app: MinimumCoreApplication) -> None:
        entered.set()
        await release.wait()
        await original(app)

    monkeypatch.setattr(MinimumCoreApplication, "stop", stop)
    before = asyncio.all_tasks()
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(wait_for_ports(ports), 2)
    await asyncio.wait_for(ports[0].entered.wait(), 2)
    task.cancel()
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runner.pending_count == 0
    assert not (asyncio.all_tasks() - before - {asyncio.current_task()})


@pytest.mark.asyncio
async def test_missing_cognition_is_blocked_and_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, request, fixture, _, _, target = setup(monkeypatch)
    app, _ = application(monkeypatch)
    no_cognition = replace(app, cognition=None)
    event = admission(app)
    fixture = replace(fixture, typed_inputs=_project(event))
    target = normal_cognition_target(
        (NormalCognitionLabCase(fixture, event),), lambda: no_cognition, PROVENANCE, "1", ()
    )
    runner = ValidationRunner((target,), POLICY)
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_sequential_iterations_release_cleanup_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, request, fixture, apps, _, target = setup(monkeypatch, internal=True)
    runner = ValidationRunner((target,), replace(POLICY, max_tasks=1, max_intervals=100))
    result = await runner.run(replace(request, repeat_count=3), fixture)
    assert result.status is RunStatus.COMPLETED
    assert len(apps) == 3 and runner.pending_count == 0
