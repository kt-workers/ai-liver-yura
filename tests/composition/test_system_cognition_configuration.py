"""本番Owner構成・provenance・失敗時の資源回収を検証する。"""

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from typing import Any

import pytest
import yaml

from app import application as bootstrap
from app.adapters.llm.production import UnavailableLLMRolePort
from app.composition import system_cognition_configuration as system
from app.config.core_contracts import CoreConfigurationError
from app.config.executive_assembly import create_executive_configuration
from app.config.llm_connections import LLMConnectionConfig
from app.domain.attention import AttentionTurnStore
from app.domain.contracts.finalization import FinalizationError
from app.domain.contracts.preconditions import PreconditionSourceRouter
from app.domain.llm import LLMRoleDescriptor
from app.domain.plugin_registry import PluginRegistryAuthority
from app.infrastructure.scheduling import SystemRuntimeClock
from app.usecases.ports.llm import LLMRolePort

class _FakeLLMAdapter:
    """既存Roleに対する型付き未構成応答と、外側の資源回収を検証する。"""

    adapter_id = "openai_responses"

    def __init__(
        self,
        *,
        preflight: Callable[[], Awaitable[None]] | None = None,
        on_release: Callable[[], None] | None = None,
    ) -> None:
        self.preflight = preflight
        self.on_release = on_release

    async def connect(
        self,
        connection: object,
        descriptors: tuple[LLMRoleDescriptor, ...],
    ) -> tuple[LLMRolePort, Callable[[], Awaitable[None]]]:
        if not isinstance(connection, LLMConnectionConfig):
            raise ValueError("接続設定の型が不正です")
        if self.preflight is not None:
            await self.preflight()

        async def release() -> None:
            if self.on_release is not None:
                self.on_release()

        return UnavailableLLMRolePort(descriptors), release


def parameters() -> dict[str, Any]:
    return dict(
        run_identity=system.CoreRunIdentity("epoch", "run"),
        activation_id="yura.core.explicit",
        fresh_start=True,
        clock=SystemRuntimeClock(),
        registry=PluginRegistryAuthority(),
        precondition_router=PreconditionSourceRouter(()),
        precondition_bindings=(),
        activity_bindings={},
        fast_rules=(),
        llm_adapters=(_FakeLLMAdapter(),),
    )


@pytest.mark.asyncio
async def test_real_factories_identity_snapshot_and_restart() -> None:
    params = parameters()
    app = await bootstrap.build_core(**params)
    assert app.core.input_context._goals is app.core.goals
    assert app.core.input_context.activities is app.core.activities
    snapshot = app.composition_snapshot
    assert app.appraisal.reducer is app.cognition.state
    assert app.appraisal.appraisal_policy is app.cognition.appraisal_policy
    assert (
        app.appraisal.decay_policy.policy_id
        == snapshot.component_bindings[0].appraisal.decay_policy_id
    )
    assert (
        app.appraisal.decay_policy.policy_revision
        == snapshot.component_bindings[0].appraisal.decay_policy_revision
    )
    assert app.executive.requirements_owner is app.cognition.requirements
    assert app.executive.initial_generation is app.cognition.requirements.current_generation()
    assert snapshot.runtime_epoch == "epoch"
    assert snapshot.system_run_id == "run"
    assert (
        snapshot.component_bindings[0].appraisal.source_context_revision
        == (app.core.input_context.snapshot().context.source_context_revision)
        == 1
    )
    assert snapshot.component_bindings[0].appraisal.runtime_epoch == "epoch"
    assert (
        snapshot.component_bindings[0].appraisal.execution_policy_id == "yura.appraisal.execution"
    )
    assert (
        snapshot.component_bindings[0].executive.execution_policy_id == "yura.executive.execution"
    )
    assert snapshot.component_bindings[0].attention_policy_id == "attention-scheduling-production"
    assert app.cognition.requirements.current_generation().serial == (
        snapshot.component_bindings[0].executive.initial_generation_serial
    )
    assert (
        snapshot.requirements_generation
        == snapshot.component_bindings[0].executive.initial_generation_identity
    )
    assert snapshot.subsystem_bindings == ()
    assert {binding.role_id for binding in snapshot.llm_connection_bindings} == {
        "input_meaning", "subjective_appraisal", "executive_deliberation",
    }
    assert {binding.connection_id for binding in snapshot.llm_connection_bindings} == {
        "yura.llm.default",
    }
    text = json.dumps(asdict(snapshot), default=str)
    for forbidden in ("test.llm.execution", "_lock", "/Users/", "credential", "raw_token"):
        assert forbidden not in text
    with pytest.raises(FrozenInstanceError):
        setattr(snapshot, "activation_id", "different")
    await app.start()
    await asyncio.gather(app.stop(), app.stop())
    with pytest.raises(FinalizationError):
        app.cognition.requirements.current_generation()
    params["registry"].snapshot()
    with pytest.raises(CoreConfigurationError, match="ACTIVATION_FAILED"):
        await app.start()
    second = await bootstrap.build_core(**parameters())
    assert second.composition_snapshot.requirements_generation != snapshot.requirements_generation
    await second.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value,code",
    [
        ("activation_id", "wrong", "ACTIVATION_FAILED"),
        ("fresh_start", False, "ACTIVATION_FAILED"),
        ("config_ref", "resources/missing.yaml", "MISSING_SYSTEM_CONFIG"),
        ("config_ref", "../secret", "INVALID_SYSTEM_CONFIG"),
    ],
)
async def test_activation_fails_without_minimum_fallback(field: str, value: Any, code: str) -> None:
    params = parameters()
    params[field] = value
    with pytest.raises(CoreConfigurationError) as caught:
        await bootstrap.build_core(**params)
    assert caught.value.code.value == code


def copy_resources(tmp_path: Path) -> None:
    shutil.copytree("config", tmp_path / "config")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference,field",
    [
        ("llm_connections", "config_revision"),
        ("appraisal_config", "config_revision"),
        ("executive_config", "config_id"),
        ("attention_policy", "policy_revision"),
        ("llm_connections", "config_id"),
        ("character_definition", "definition_revision"),
    ],
)
async def test_reference_mismatch(tmp_path: Path, reference: str, field: str) -> None:
    copy_resources(tmp_path)
    path = tmp_path / system.CORE_RESOURCE
    data = yaml.safe_load(path.read_text())
    data[reference][field] = "different" if field.endswith("id") else 2
    path.write_text(yaml.safe_dump(data))
    params = parameters()
    params["resource_root"] = tmp_path
    with pytest.raises(CoreConfigurationError, match="INVALID_SYSTEM_CONFIG"):
        await bootstrap.build_core(**params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["appraisal", "executive", "attention", "provider", "cognition", "core", "snapshot"]
)
async def test_failure_stages_reclaim_owners(monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    params = parameters()
    events: list[str] = []
    bindings: list[Any] = []
    original_executive = create_executive_configuration
    original_attention = AttentionTurnStore

    def executive(*args: Any, **kwargs: Any) -> Any:
        if stage == "executive":
            raise ValueError("private-internal-detail")
        value = original_executive(*args, **kwargs)
        bindings.append(value)
        return value

    def attention(*args: Any, **kwargs: Any) -> Any:
        if stage == "attention":
            raise ValueError("private-internal-detail")
        value = original_attention(*args, **kwargs)
        return value

    async def provider() -> None:
        if stage == "provider":
            raise ValueError("private-internal-detail")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("private-internal-detail")

    monkeypatch.setattr(system, "create_executive_configuration", executive)
    monkeypatch.setattr(system, "AttentionTurnStore", attention)
    params["llm_adapters"] = (_FakeLLMAdapter(preflight=provider, on_release=lambda: events.append("provider")),)
    if stage == "appraisal":
        monkeypatch.setattr(system, "build_appraisal_configuration", fail)
    if stage == "cognition":
        monkeypatch.setattr(system, "CoreCognitionConfiguration", fail)
    if stage == "core":
        monkeypatch.setattr(bootstrap, "_compose_core", fail)
    if stage == "snapshot":
        monkeypatch.setattr(system, "_snapshot", fail)
    with pytest.raises(CoreConfigurationError) as caught:
        await bootstrap.build_core(**params)
    assert "private-internal-detail" not in str(caught.value)
    for binding in bindings:
        with pytest.raises(FinalizationError):
            binding.requirements_owner.current_generation()
    assert events == (["provider"] if stage in ("cognition", "core", "snapshot") else [])
    params["registry"].snapshot()


@pytest.mark.asyncio
async def test_reverse_cleanup_continues_after_failure() -> None:
    ledger = system._OwnedResources()
    events: list[int] = []
    for i in range(4):

        async def close(i: int = i) -> None:
            events.append(i)
            if i == 2:
                raise ValueError("private-detail")

        ledger.actions.append(close)
    with pytest.raises(CoreConfigurationError):
        await ledger.close()
    assert events == [3, 2, 1, 0]
    await ledger.close()
    assert events == [3, 2, 1, 0]


@pytest.mark.asyncio
async def test_cancel_stop_waits_for_owned_cleanup() -> None:
    app = await bootstrap.build_core(**parameters())
    entered, finish = asyncio.Event(), asyncio.Event()

    async def slow() -> None:
        entered.set()
        await finish.wait()

    app._owned.actions.insert(0, slow)
    task = asyncio.create_task(app.stop())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await app.stop()
    assert not app._owned.actions


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_start_failure_uses_same_cleanup(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    app = await bootstrap.build_core(**parameters())
    entered = asyncio.Event()

    async def start(self: bootstrap.CoreComponents) -> None:
        entered.set()
        if cancel:
            await asyncio.Future()
        raise ValueError("private-detail")

    monkeypatch.setattr(bootstrap, "start_core", start)
    task = asyncio.create_task(app.start())
    await entered.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else CoreConfigurationError):
        await task
    assert not app._owned.actions
    with pytest.raises(FinalizationError):
        app.cognition.requirements.current_generation()


@pytest.mark.asyncio
async def test_generation_change_before_publication_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = bootstrap._compose_core

    def compose(*args: Any, **kwargs: Any) -> Any:
        core = original(*args, **kwargs)
        kwargs["cognition"].requirements.finalization_participant.retire()
        return core

    monkeypatch.setattr(bootstrap, "_compose_core", compose)
    with pytest.raises(CoreConfigurationError, match="INITIALIZATION_FAILED"):
        await bootstrap.build_core(**parameters())


def test_minimum_core_boot_stays_input_meaning_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YURA_OPENAI_API_KEY", raising=False)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("minimum起動がcore構成を参照しました")

    monkeypatch.setattr(system, "load_core_config", forbidden)
    core = bootstrap.build_core_runtime(cognition=None)
    assert core.cognition is None
    assert core.bridge is not None and core.cognition is None


@pytest.mark.asyncio
async def test_cancel_during_provider_construction_reclaims_previous_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = parameters()
    constructed: list[Any] = []
    entered = asyncio.Event()

    def executive(*args: Any, **kwargs: Any) -> Any:
        result = create_executive_configuration(*args, **kwargs)
        constructed.append(result)
        return result

    async def blocked() -> None:
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(system, "create_executive_configuration", executive)
    params["llm_adapters"] = (_FakeLLMAdapter(preflight=blocked),)
    task = asyncio.create_task(bootstrap.build_core(**params))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(FinalizationError):
        constructed[0].requirements_owner.current_generation()
    params["registry"].snapshot()


@pytest.mark.asyncio
async def test_owned_cleanup_actual_order(monkeypatch: pytest.MonkeyPatch) -> None:
    params = parameters()
    events: list[str] = []
    from app.config.executive_assembly import ExecutiveProductionBinding
    from app.domain.contracts.finalization import AuthorityFinalizationParticipant

    original_close = ExecutiveProductionBinding.close
    original_retire = AuthorityFinalizationParticipant.retire
    original_stop = system.CoreApplication.stop

    def close(binding: ExecutiveProductionBinding) -> None:
        events.append("executive")
        original_close(binding)

    def retire(participant: Any) -> None:
        events.append("retire")
        original_retire(participant)

    async def stop(core: system.CoreApplication) -> None:
        events.append("core")
        await original_stop(core)

    monkeypatch.setattr(ExecutiveProductionBinding, "close", close)
    monkeypatch.setattr(AuthorityFinalizationParticipant, "retire", retire)
    monkeypatch.setattr(system.CoreApplication, "stop", stop)
    params["llm_adapters"] = (_FakeLLMAdapter(on_release=lambda: events.append("provider")),)
    app = await bootstrap.build_core(**params)
    await app.stop()
    assert events[:4] == ["core", "provider", "retire", "executive"]
    assert events.count("provider") == events.count("executive") == events.count("core") == 1


@pytest.mark.asyncio
async def test_symlink_resource_cannot_escape_root(tmp_path: Path) -> None:
    copy_resources(tmp_path)
    source = tmp_path / "config/appraisal.yaml"
    source.unlink()
    source.symlink_to(Path("config/appraisal.yaml").resolve())
    params = parameters()
    params["resource_root"] = tmp_path
    with pytest.raises(CoreConfigurationError, match="INVALID_SYSTEM_CONFIG"):
        await bootstrap.build_core(**params)
