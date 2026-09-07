"""実際のBrain実行とプロセス境界で、早期起動の成立を検証する。"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml

from app import bootstrap
from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm import production
from app.adapters.llm.production import UnavailableLLMRolePort
from app.bootstrap import (
    InputMeaningBrainModulePort,
    InputMeaningBrainWorkPayload,
    UnavailableInputMeaningLiveContextPort,
    build_minimum_core,
)
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.config.minimum_brain import load_minimum_brain_config
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
    BrainWorkEnvelope,
    BrainWorkPriority,
    BrainWorkStatus,
)
from app.domain.contracts import CapabilityAvailability, EventEnvelope, RevisionVector
from app.domain.input_gateway import (
    InputModality,
    InputPermission,
    InputSourceState,
    NormalizedInputEvent,
)
from app.domain.input_meaning import (
    OUTPUT_SCHEMA,
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    InputMeaningInterpreter,
    ReferenceContext,
)
from app.domain.llm import (
    LLMFailureCode,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from app.runtime.kernel import CancellationToken, SystemRuntimeClock
from app.runtime.lifecycle import RuntimeLifecycle

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(production, "os", SimpleNamespace(environ={}))


def work() -> BrainIntegrationWork:
    event = NormalizedInputEvent(
        EventEnvelope(
            "event-1",
            "input.text.utterance",
            "chat",
            NOW,
            "trace-1",
            RevisionVector(4),
            {
                "content": {"text": "こんにちは"},
                "modality": "text",
                "source": {"source_id": "chat"},
            },
        ),
        InputModality.TEXT,
        InputSourceState("chat", "user", CapabilityAvailability.AVAILABLE, InputPermission.GRANTED),
    )
    return BrainIntegrationWork(
        "work-1",
        BrainIntegrationModule.INPUT_MEANING,
        BrainIntegrationLane.FOREGROUND_INTERACTION,
        BrainWorkEnvelope(
            "trace-1", "trigger-1", ("event-1",), 4, None, None, BrainWorkPriority.DIRECT_USER, NOW
        ),
        InputMeaningBrainWorkPayload(event, ReferenceContext(4, ()), "request-1"),
    )


class CountingUnavailableContext(UnavailableInputMeaningLiveContextPort):
    def __init__(self) -> None:
        self.calls = 0

    async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
        self.calls += 1
        return await super().current_freshness_stamp()


class SuccessfulPort:
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.SUCCEEDED,
            request.revisions,
            datetime.now(timezone.utc),
            request.trace_id,
            request.execution_policy.model_class,
            1,
            LLMTokenUsage(1, 1),
            StructuredPayload(
                OUTPUT_SCHEMA,
                {
                    "speech_act": "statement",
                    "primary_intent": "social",
                    "expected_response": "none",
                    "target_ref": None,
                    "entities": (),
                    "references": (),
                    "information": (),
                    "negated": False,
                    "hypothetical": False,
                    "temporal_relation": "present",
                    "confidence": 0.9,
                    "unresolved_fields": (),
                },
            ),
            started_at=request.created_at,
        )


def test_production_binding_through_brain_preserves_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_provider(monkeypatch)
    reads = 0
    original = CoreInputReferenceContextBinding.current_freshness_stamp

    async def observed(self: CoreInputReferenceContextBinding) -> InputMeaningFreshnessStamp:
        nonlocal reads
        reads += 1
        return await original(self)

    monkeypatch.setattr(CoreInputReferenceContextBinding, "current_freshness_stamp", observed)

    async def scenario() -> None:
        baseline = asyncio.all_tasks()
        app = build_minimum_core()
        assert isinstance(app.llm, UnavailableLLMRolePort)
        await app.start()
        try:
            value = work()
            assert app.bridge.is_fresh(value)
            assert app.brain.submit(value).accepted
            outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
            assert outcome.status is BrainWorkStatus.COMPLETED
            assert isinstance(outcome.result, InputMeaningInterpretationResult)
            result = outcome.result
            assert result.role_status is LLMRoleStatus.FAILED
            assert result.role_failure is not None
            assert result.role_failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
            assert result.meaning is None and result.boundary_failure is None
            assert (result.request_id, result.trace_id, result.source_event_id) == (
                "request-1",
                "trace-1",
                "event-1",
            )
            assert app.bridge.is_fresh(value)
            assert reads == 0
        finally:
            await app.stop()
        assert not (asyncio.all_tasks() - baseline)

    asyncio.run(scenario())


def test_success_with_unavailable_live_context_is_owner_rejection() -> None:
    async def scenario() -> None:
        config = load_minimum_brain_config(
            (ROOT / "resources/config/v2/minimum_brain.yaml").read_bytes()
        )
        live = CountingUnavailableContext()
        bridge = InputMeaningBrainModulePort(
            InputMeaningInterpreter(
                SuccessfulPort(),
                live,
                config.input_meaning_policy,
            )
        )
        runtime = BrainIntegrationRuntime(SystemRuntimeClock(), config.integration_policy)
        runtime.register_module(BrainIntegrationModule.INPUT_MEANING, bridge)
        await runtime.start()
        try:
            assert runtime.submit(work()).accepted
            outcome = await asyncio.wait_for(runtime.next_outcome(), 2)
            assert outcome.status is BrainWorkStatus.COMPLETED
            assert isinstance(outcome.result, InputMeaningInterpretationResult)
            result = outcome.result
            assert result.role_status is LLMRoleStatus.SUCCEEDED
            assert result.meaning is None and result.role_failure is None
            assert result.boundary_failure is not None
            assert result.boundary_failure.code is LLMFailureCode.REJECTED
            assert live.calls == 1
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def malformed(case: str) -> BrainIntegrationWork:
    value = work()
    payload = cast(InputMeaningBrainWorkPayload, value.payload)
    if case == "module":
        return replace(value, module=BrainIntegrationModule.EXECUTIVE)
    if case == "lane":
        return replace(value, lane=BrainIntegrationLane.COGNITIVE_NORMAL)
    if case == "event_ids":
        return replace(value, envelope=replace(value.envelope, source_event_ids=("different",)))
    if case == "work_revision":
        return replace(value, envelope=replace(value.envelope, source_context_revision=5))
    if case == "context_revision":
        return replace(value, payload=replace(payload, reference_context=ReferenceContext(5, ())))
    if case == "event_revision":
        event = replace(
            payload.event, envelope=replace(payload.event.envelope, revisions=RevisionVector(5))
        )
        return replace(value, payload=replace(payload, event=event))
    if case == "trace":
        return replace(value, envelope=replace(value.envelope, trace_id="different"))
    if case == "blank_request":
        return replace(value, payload=replace(payload, request_id=" "))
    return replace(value, payload=object())


@pytest.mark.parametrize(
    "case",
    [
        "module",
        "lane",
        "event_ids",
        "work_revision",
        "context_revision",
        "event_revision",
        "trace",
        "blank_request",
        "payload_type",
    ],
)
def test_invalid_composition_is_failed_not_stale(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    no_provider(monkeypatch)

    async def scenario() -> None:
        app = build_minimum_core()
        value = malformed(case)
        with pytest.raises(ValueError):
            app.bridge.is_fresh(value)
        with pytest.raises(ValueError):
            await app.bridge.execute(value, CancellationToken())
        runtime = BrainIntegrationRuntime(SystemRuntimeClock(), app.config.integration_policy)
        # 誤った登録も検査できるよう、試験用Runtimeだけに対象を明示登録する。
        runtime.register_module(value.module, app.bridge)
        await runtime.start()
        try:
            assert runtime.submit(value).accepted
            outcome = await asyncio.wait_for(runtime.next_outcome(), 2)
            assert outcome.status is BrainWorkStatus.FAILED
            assert outcome.result is None
            assert outcome.error == "ValueError"
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_runtime_cancellation_propagates_and_reaps() -> None:
    async def scenario() -> None:
        baseline = asyncio.all_tasks()
        entered, cancelled = asyncio.Event(), asyncio.Event()

        class WaitingPort:
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                raise AssertionError("待機中の要求が通常完了してはなりません")

        config = load_minimum_brain_config(
            (ROOT / "resources/config/v2/minimum_brain.yaml").read_bytes()
        )
        bridge = InputMeaningBrainModulePort(
            InputMeaningInterpreter(
                WaitingPort(),
                CountingUnavailableContext(),
                config.input_meaning_policy,
            )
        )
        runtime = BrainIntegrationRuntime(SystemRuntimeClock(), config.integration_policy)
        runtime.register_module(BrainIntegrationModule.INPUT_MEANING, bridge)
        await runtime.start()
        try:
            assert runtime.submit(work()).accepted
            await asyncio.wait_for(entered.wait(), 2)
            assert runtime.cancel("work-1", "試験からの取消")
            outcome = await asyncio.wait_for(runtime.next_outcome(), 2)
            assert outcome.status is BrainWorkStatus.CANCELLED
            assert outcome.result is None and cancelled.is_set()
        finally:
            await runtime.stop()
        assert not (asyncio.all_tasks() - baseline)

    asyncio.run(scenario())


def test_canonical_composition_repeated_start_stop_has_no_pending_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_provider(monkeypatch)

    async def scenario() -> None:
        for _ in range(3):
            baseline = asyncio.all_tasks()
            app = build_minimum_core()
            assert app.character_definition == load_character_definition_yaml(
                (ROOT / app.config.character_definition_path).read_bytes(),
            )
            assert app.character_definition.definition_revision >= 1
            assert app.lifecycle.shutdown_policy is app.config.shutdown_policy
            assert app.brain.policy is app.config.integration_policy
            assert app.lifecycle.snapshots() == ()
            await app.start()
            try:
                assert asyncio.all_tasks() - baseline
                for number, module in enumerate(BrainIntegrationModule):
                    if module is BrainIntegrationModule.INPUT_MEANING:
                        continue
                    candidate = replace(work(), work_id=f"absent-{number}", module=module)
                    assert not app.brain.submit(candidate).accepted
                    outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
                    assert outcome.status is BrainWorkStatus.REJECTED
                    assert outcome.error == "UNREGISTERED_MODULE"
            finally:
                await app.stop()
                await app.stop()
            assert app.lifecycle.snapshots() == ()
            assert not (asyncio.all_tasks() - baseline)

    asyncio.run(scenario())


def test_configured_provider_missing_config_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "試験用の非秘密識別文字列"
    monkeypatch.setattr(production, "os", SimpleNamespace(environ={"OPENAI_API_KEY": sentinel}))
    with pytest.raises(ValueError, match="役割設定") as caught:
        build_minimum_core()
    assert sentinel not in str(caught.value)


def test_stop_failure_propagates_but_lifecycle_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    no_provider(monkeypatch)
    closed = False

    async def failed_stop(self: BrainIntegrationRuntime) -> None:
        raise RuntimeError("試験用の停止失敗")

    async def close(self: RuntimeLifecycle) -> None:
        nonlocal closed
        closed = True

    monkeypatch.setattr(BrainIntegrationRuntime, "stop", failed_stop)
    monkeypatch.setattr(RuntimeLifecycle, "close", close)
    with pytest.raises(RuntimeError, match="停止失敗"):
        asyncio.run(build_minimum_core().stop())
    assert closed


def test_run_loop_cancellation_cleans_signals_and_owned_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_provider(monkeypatch)
    original_start = bootstrap.MinimumCoreApplication.start

    async def scenario() -> None:
        baseline = asyncio.all_tasks()
        started = asyncio.Event()
        previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

        async def start(self: bootstrap.MinimumCoreApplication) -> None:
            await original_start(self)
            started.set()

        monkeypatch.setattr(bootstrap.MinimumCoreApplication, "start", start)
        runner = asyncio.create_task(bootstrap.run_minimum_core())
        try:
            await asyncio.wait_for(started.wait(), 2)
            assert not runner.done()
        finally:
            runner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await runner
        assert not (asyncio.all_tasks() - baseline)
        assert {s: signal.getsignal(s) for s in previous} == previous

    asyncio.run(scenario())


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
def test_entrypoint_subprocess_graceful_shutdown(stop_signal: signal.Signals) -> None:
    async def scenario() -> None:
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)
        env["PYTHONASYNCIODEBUG"] = "1"
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app",
            cwd=ROOT,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert child.stdout is not None
            ready = await asyncio.wait_for(child.stdout.readline(), 10)
            assert ready.decode().strip() == "最小Coreの起動が完了しました。"
            assert child.returncode is None
            child.send_signal(stop_signal)
            stdout, stderr = await asyncio.wait_for(child.communicate(), 8)
            assert child.returncode == 0
            assert stdout == b""
            assert stderr == b""
        finally:
            if child.returncode is None:
                child.kill()
                await child.communicate()

    asyncio.run(scenario())


def test_descriptor_and_interpreter_receive_the_same_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.input_meaning import InputMeaningLiveContextPort, InputMeaningPolicy
    from app.domain.llm import LLMRoleDescriptor
    from app.usecases.ports.llm import LLMRolePort

    no_provider(monkeypatch)
    observed: list[InputMeaningPolicy] = []
    from app.domain.input_meaning.interpreter import descriptor as original_descriptor

    def descriptor(policy: InputMeaningPolicy) -> LLMRoleDescriptor:
        observed.append(policy)
        return original_descriptor(policy)

    def interpreter(
        port: LLMRolePort,
        live_context: InputMeaningLiveContextPort,
        policy: InputMeaningPolicy,
    ) -> InputMeaningInterpreter:
        observed.append(policy)
        return InputMeaningInterpreter(port, live_context, policy)

    monkeypatch.setattr(bootstrap, "descriptor", descriptor)
    monkeypatch.setattr(bootstrap, "InputMeaningInterpreter", interpreter)
    app = build_minimum_core()
    assert len(observed) == 2
    assert all(policy is app.config.input_meaning_policy for policy in observed)


def test_running_generation_does_not_reload_changed_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    no_provider(monkeypatch)
    path = tmp_path / "minimum_brain.yaml"
    path.write_bytes((ROOT / "resources/config/v2/minimum_brain.yaml").read_bytes())

    async def scenario() -> None:
        app = build_minimum_core(path)
        config = app.config
        await app.start()
        try:
            path.write_text("不正な新しい設定")
            assert app.config is config
            assert app.brain.policy is config.integration_policy
            assert app.brain.submit(work()).accepted
            assert (
                await asyncio.wait_for(app.brain.next_outcome(), 2)
            ).status is BrainWorkStatus.COMPLETED
            with pytest.raises(ValueError):
                build_minimum_core(path)
        finally:
            await app.stop()

    asyncio.run(scenario())


def test_minimum_core_runs_with_optional_surface_imports_forbidden() -> None:
    """パッケージを除去せず、画面や検証基盤への推移的な読込を検出する。"""
    script = r"""
import importlib.abc
import runpy
import sys

forbidden = (
    "app.subsystems", "tools.validation_lab", "PyQt6", "PySide6",
    "aiohttp.web", "aiohttp.web_runner", "app.adapters.avatar", "app.adapters.tts",
)
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in forbidden):
            raise AssertionError("最小本体が任意の外部実装を読み込みました: " + fullname)
sys.meta_path.insert(0, Boundary())
import pytest
namespace = runpy.run_path("tests/system_integration/test_early_boot.py")
with pytest.MonkeyPatch.context() as patch:
    namespace["test_production_binding_through_brain_preserves_unavailable"](patch)
    namespace["test_canonical_composition_repeated_start_stop_has_no_pending_tasks"](patch)
assert not any(
    module == name or module.startswith(name + ".")
    for module in sys.modules for name in forbidden
)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "" and result.stderr == ""


def test_file_edit_takes_effect_only_in_next_core_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """有効な設定編集を次の構成で読み、稼働中の方針を変更しない。"""
    no_provider(monkeypatch)
    path = tmp_path / "minimum_brain.yaml"
    original = (ROOT / "resources/config/v2/minimum_brain.yaml").read_bytes()
    path.write_bytes(original)

    async def scenario() -> None:
        baseline = asyncio.all_tasks()
        first = build_minimum_core(path)
        await first.start()
        try:
            edited = yaml.safe_load(original)
            edited["config_revision"] = 2
            edited["scheduler"]["policy_revision"] = 2
            edited["scheduler"]["max_priority_burst"] = 9
            path.write_text(yaml.safe_dump(edited, allow_unicode=True))
            assert first.config.config_revision == 1
            assert first.config.scheduler_policy.policy_revision == 1
            assert first.config.scheduler_policy.max_priority_burst == 8
            assert first.brain.submit(work()).accepted
            outcome = await asyncio.wait_for(first.brain.next_outcome(), 2)
            assert outcome.status is BrainWorkStatus.COMPLETED
        finally:
            await first.stop()
        second = build_minimum_core(path)
        assert second.config.config_revision == 2
        assert second.config.scheduler_policy.policy_revision == 2
        assert second.config.scheduler_policy.max_priority_burst == 9
        await second.start()
        try:
            assert second.brain.submit(work()).accepted
            outcome = await asyncio.wait_for(second.brain.next_outcome(), 2)
            assert outcome.status is BrainWorkStatus.COMPLETED
        finally:
            await second.stop()
        assert not (asyncio.all_tasks() - baseline)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["initialization", "disconnect", "delay", "stop"])
def test_external_test_client_lifecycle_does_not_stop_core(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """最小利用者の失敗・停止と本体停止を分ける。実GUI通信の試験ではない。"""
    no_provider(monkeypatch)

    async def scenario() -> None:
        baseline = asyncio.all_tasks()
        app = build_minimum_core()
        config = app.config
        entered = asyncio.Event()
        release = asyncio.Event()

        async def external_client() -> None:
            if failure == "initialization":
                raise RuntimeError("試験用利用者の初期化失敗")
            assert app.brain.submit(replace(work(), work_id="external-1")).accepted
            entered.set()
            if failure == "disconnect":
                raise ConnectionError("試験用利用者の切断")
            await release.wait()

        await app.start()
        client = asyncio.create_task(external_client())
        try:
            if failure == "initialization":
                with pytest.raises(RuntimeError, match="初期化失敗"):
                    await client
            else:
                await asyncio.wait_for(entered.wait(), 2)
                if failure == "disconnect":
                    with pytest.raises(ConnectionError, match="切断"):
                        await client
                elif failure == "stop":
                    client.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await client
                else:
                    assert not client.done()
            assert app.brain.submit(replace(work(), work_id="independent-1")).accepted
            expected = {"independent-1"}
            if failure != "initialization":
                expected.add("external-1")
            observed = set()
            for _ in expected:
                outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
                assert outcome.status is BrainWorkStatus.COMPLETED
                assert isinstance(outcome.result, InputMeaningInterpretationResult)
                assert outcome.result.role_failure is not None
                assert outcome.result.role_failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
                observed.add(outcome.work_id)
            assert observed == expected
            assert app.config is config
            if failure == "delay":
                assert not client.done()
        finally:
            release.set()
            if not client.done():
                client.cancel()
            await asyncio.gather(client, return_exceptions=True)
            await app.stop()
        assert not (asyncio.all_tasks() - baseline)

    asyncio.run(scenario())


def test_replacement_and_concurrent_clients_use_the_same_public_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """別の最小利用者と併用しても、受付・実行・結果は本体の所有者に委ねる。"""
    no_provider(monkeypatch)

    async def scenario() -> None:
        baseline = asyncio.all_tasks()
        app = build_minimum_core()
        config = app.config

        async def submit_batch(client_id: str) -> None:
            for number in range(3):
                value = work()
                request_id = f"{client_id}-{number}"
                payload = cast(InputMeaningBrainWorkPayload, value.payload)
                value = replace(
                    value,
                    work_id=request_id,
                    payload=replace(payload, request_id=request_id),
                )
                assert app.brain.submit(value).accepted
                await asyncio.sleep(0)

        await app.start()
        try:
            # 先行利用者を終了し、別の利用者へ交換した後で二者を併用する。
            await submit_batch("first")
            await asyncio.gather(submit_batch("replacement"), submit_batch("additional"))
            expected = {
                f"{name}-{n}" for name in ("first", "replacement", "additional") for n in range(3)
            }
            observed = set()
            for _ in expected:
                outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
                assert outcome.status is BrainWorkStatus.COMPLETED
                assert isinstance(outcome.result, InputMeaningInterpretationResult)
                assert outcome.result.request_id == outcome.work_id
                assert outcome.result.meaning is None
                assert outcome.result.role_failure is not None
                assert outcome.result.role_failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
                observed.add(outcome.work_id)
            assert observed == expected
            assert app.config is config
        finally:
            await app.stop()
        assert not (asyncio.all_tasks() - baseline)

    asyncio.run(scenario())
