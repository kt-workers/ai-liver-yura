"""製品の入口、検証証拠の区別、並行実行と取消の直接検証。"""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.adapters.llm.production import UnavailableLLMRolePort
from app.domain.contracts.common import freeze_json
from app.domain.input_meaning import InputMeaningFreshnessStamp, build_request
from app.domain.input_meaning.interpreter import descriptor
from app.subsystems.validation.contracts import (
    DelayInjection,
    Gate,
    LabMode,
    LabPolicy,
    LabRunSpec,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from app.subsystems.validation.input_meaning import InputMeaningLabCase, input_meaning_target
from app.subsystems.validation.runtime import LabTarget, RunContext, ValidationRunner
from tests.domain.input_meaning import test_input_meaning as meaning

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
POLICY = LabPolicy(3, 4, 16, 100_000, 1.0, 5)
PROVENANCE = ProductionTargetProvenance("a" * 40, "test", ("contract.v1",), ())
FIXTURE = ValidationFixture(
    "scenario", "1", freeze_json({"value": 1}), freeze_json({"source": "入力に由来する説明"})
)


def spec() -> LabRunSpec:
    return LabRunSpec("run", "test", LabMode.ISOLATION, "target", "1", "scenario", "1", (), 1, NOW)


async def success(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
    return TargetObservation(RunStatus.COMPLETED, Gate.PASS, fixture.typed_inputs)


def target() -> LabTarget:
    return LabTarget("target", "1", frozenset({LabMode.ISOLATION}), (), PROVENANCE, success)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "run_spec",
    [
        replace(spec(), mode=LabMode.INTEGRATED),
        replace(spec(), target_contract_revision="2"),
        replace(spec(), fixture_revision="2"),
        replace(spec(), provider_policy_refs=("other",)),
    ],
)
async def test_mismatched_origin_never_invokes_target(run_spec: LabRunSpec) -> None:
    called = False

    async def forbidden(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        nonlocal called
        called = True
        return await success(context, fixture)

    runner = ValidationRunner((replace(target(), run=forbidden),), POLICY)
    result = await runner.run(run_spec, FIXTURE)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert result.machine_gate is Gate.NOT_RUN
    assert result.timeline == () and not called


@pytest.mark.asyncio
async def test_exports_preserve_scope_and_do_not_promote_machine_to_human() -> None:
    runner = ValidationRunner((target(),), POLICY)
    result = await runner.run(spec(), FIXTURE)
    encoded = json.loads(result.export_json(POLICY.max_export_bytes))
    assert encoded["run_spec"]["mode"] == "ISOLATION"
    assert encoded["target_provenance"]["git_head"] == "a" * 40
    assert encoded["human_evaluation"]["status"] == "UNRATED"
    assert encoded["human_context"]["source"] == "入力に由来する説明"
    with pytest.raises(ValueError, match="容量"):
        result.export_json(10)
    assert runner.take_result("run") is result


@pytest.mark.asyncio
async def test_exception_details_and_sdk_values_are_not_exported() -> None:
    async def broken(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        raise RuntimeError("検証用の非公開例外本文")

    runner = ValidationRunner((replace(target(), run=broken),), POLICY)
    result = await runner.run(spec(), FIXTURE)
    assert result.status is RunStatus.HARNESS_FAILED
    assert "非公開例外本文" not in result.export_json(POLICY.max_export_bytes)
    with pytest.raises(ValueError):
        TargetObservation(RunStatus.COMPLETED, Gate.PASS, object())  # type: ignore[arg-type]
    unsafe = replace(result, fixture=replace(FIXTURE, typed_inputs={"api_key": "試験値"}))
    with pytest.raises(ValueError, match="非公開"):
        unsafe.export_json(POLICY.max_export_bytes)


@pytest.mark.asyncio
async def test_stage_overlap_is_measured_while_sibling_is_waiting() -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def concurrent(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        async def slow() -> object:
            entered.set()
            await release.wait()
            return None

        context.spawn("slow", slow)
        await entered.wait()
        await context.stage("fast", lambda: asyncio.sleep(0))
        release.set()
        return await success(context, fixture)

    runner = ValidationRunner((replace(target(), run=concurrent),), POLICY)
    result = await runner.run(spec(), FIXTURE)
    intervals = {interval.stage: interval for interval in result.timeline}
    assert intervals["slow"].overlaps(intervals["fast"])
    assert result.status is RunStatus.COMPLETED


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "timeout", "close"])
async def test_run_termination_reaps_children_without_cancelling_foreign_tasks(mode: str) -> None:
    entered = asyncio.Event()
    own_closed = asyncio.Event()
    foreign = asyncio.create_task(asyncio.Event().wait())

    async def blocked(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        async def child() -> None:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                own_closed.set()

        context.spawn("owned", child)
        await entered.wait()
        await asyncio.Event().wait()
        return await success(context, fixture)

    policy = replace(POLICY, timeout_seconds=0.03 if mode == "timeout" else 1.0)
    runner = ValidationRunner((replace(target(), run=blocked),), policy)
    try:
        task = asyncio.create_task(runner.run(spec(), FIXTURE))
        await entered.wait()
        if mode == "cancel":
            await runner.cancel("run")
        elif mode == "close":
            await runner.close()
        result = await asyncio.wait_for(task, 0.5)
        assert result.status is (RunStatus.TIMED_OUT if mode == "timeout" else RunStatus.CANCELLED)
        assert own_closed.is_set() and not foreign.done()
        assert runner.pending_count == 0
    finally:
        foreign.cancel()
        await asyncio.gather(foreign, return_exceptions=True)
        await runner.close()


@pytest.mark.asyncio
async def test_port_delay_preserves_result_and_is_recorded_in_spec() -> None:
    marker = object()

    async def observed(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        async def delegate() -> object:
            return marker

        assert await context.invoke_port("provider", delegate) is marker
        return await success(context, fixture)

    runner = ValidationRunner(
        (replace(target(), run=observed, delay_stages=frozenset({"provider"})),), POLICY
    )
    result = await runner.run(
        replace(spec(), delay_injections=(DelayInjection("provider", 0.01, 1),)), FIXTURE
    )
    span = next(x for x in result.timeline if x.stage == "provider")
    assert span.completed_ns - span.started_ns >= 10_000_000
    assert "delay_injections" in result.export_json(POLICY.max_export_bytes)


@pytest.mark.asyncio
async def test_real_input_meaning_entrypoint_and_production_unavailable_port() -> None:
    event, refs, policy = meaning.event(), meaning.context(), meaning.policy()
    request = build_request(
        event,
        refs,
        request_id="r",
        trace_id=event.envelope.trace_id,
        created_at=meaning.NOW,
        policy=policy,
    )
    fixture = replace(FIXTURE, typed_inputs=request.input.value)

    class NoLiveRead:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            pytest.fail("提供サービス不在で現在世代を読んではなりません")

    binding = input_meaning_target(
        (InputMeaningLabCase(fixture, event, refs, meaning.NOW),),
        UnavailableLLMRolePort((descriptor(policy),), now=lambda: meaning.NOW),
        NoLiveRead(),
        policy,
        PROVENANCE,
        "1",
        (),
    )
    runner = ValidationRunner((binding,), POLICY)
    result = await runner.run(replace(spec(), target_module="input_meaning"), fixture)
    assert result.status is RunStatus.PROVIDER_FAILED
    output = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"][0][
        "typed_outputs"
    ]
    assert output["meaning"] is None
    assert output["role_failure"]["code"] == "provider_unavailable"
    assert [x.stage for x in result.timeline] == ["input_meaning.llm", "target"]


@pytest.mark.asyncio
async def test_repeated_runs_require_releasing_retained_evidence() -> None:
    runner = ValidationRunner((target(),), replace(POLICY, max_retained_results=1))
    await runner.run(spec(), FIXTURE)
    with pytest.raises(ValueError, match="保持上限"):
        await runner.run(replace(spec(), run_id="next"), FIXTURE)
    runner.take_result("run")
    result = await runner.run(replace(spec(), run_id="next"), FIXTURE)
    assert result.status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_child_exception_cannot_be_silently_reported_as_pass() -> None:
    async def failing(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        async def child() -> None:
            raise RuntimeError("非公開の子処理例外")

        context.spawn("child", child)
        return await success(context, fixture)

    runner = ValidationRunner((replace(target(), run=failing),), POLICY)
    result = await runner.run(spec(), FIXTURE)
    assert result.status is RunStatus.HARNESS_FAILED
    assert result.machine_gate is Gate.NOT_RUN
    assert "非公開の子処理例外" not in result.export_json(POLICY.max_export_bytes)


@pytest.mark.asyncio
async def test_unverified_iteration_is_not_upgraded_by_later_pass() -> None:
    async def mixed(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        gate = Gate.NOT_RUN if context.iteration == 0 else Gate.PASS
        return TargetObservation(RunStatus.COMPLETED, gate, None)

    runner = ValidationRunner((replace(target(), run=mixed),), POLICY)
    result = await runner.run(replace(spec(), repeat_count=2), FIXTURE)
    assert result.machine_gate is Gate.NOT_RUN


def test_provenance_rejects_dirty_production_sources(tmp_path: object) -> None:
    from pathlib import Path
    from subprocess import run

    from app.subsystems.validation.provenance import capture_production_provenance

    repository = Path(str(tmp_path))

    def git(*args: str) -> None:
        run(["git", "-C", str(repository), *args], check=True, capture_output=True)

    git("init", "-b", "test")
    (repository / "product.py").write_text("value = 1\n")
    git("add", "product.py")
    git(
        "-c",
        "user.name=検証",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "検証用の製品",
    )
    provenance = capture_production_provenance(repository, ("product.py",), ("contract",), ())
    assert len(provenance.git_head) == 40
    (repository / "product.py").write_text("value = 2\n")
    with pytest.raises(ValueError, match="未記録"):
        capture_production_provenance(repository, ("product.py",), ("contract",), ())


@pytest.mark.asyncio
async def test_real_game_loop_applies_actions_while_peer_is_waiting() -> None:
    from app.subsystems.validation.game_skill import game_fixture, game_target

    runner = ValidationRunner((game_target(PROVENANCE),), POLICY)
    fixture = game_fixture()
    result = await runner.run(
        replace(
            spec(),
            target_module="game_skill",
            scenario_id=fixture.scenario_id,
        ),
        fixture,
    )
    assert result.machine_gate is Gate.PASS
    output = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"][0][
        "typed_outputs"
    ]
    assert len(output["reports"]) == 3
    assert output["pending_game_tasks"] == 0
    assert all(report["effect_state"] == "applied" for report in output["reports"])
