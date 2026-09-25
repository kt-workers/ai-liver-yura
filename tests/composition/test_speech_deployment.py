"""設定からS2までを本番policyで接続し、外部I/Oだけを隔離する。"""

import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app import bootstrap
from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm.production import UnavailableLLMRolePort
from app.adapters.llm.speech_semantics import SpeechSemanticsProviderPort
from app.composition.speech import CoreSpeechContextReaders
from app.composition.speech_deployment import (
    SpeechDeploymentRegistry,
    SpeechDeploymentRequest,
    create_speech_deployment,
)
from app.composition.speech_production_configuration import SpeechProductionPorts
from app.composition.speech_semantics_policy import build_speech_semantics_policy_owner_v1
from app.composition.system_cognition_configuration import S2RunIdentity
from app.config.layered import ConfigurationError
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity
from app.domain.speech_semantics.schemas import (
    PROVIDER_OUTPUT_SCHEMA,
    speech_semantics_instructions,
)
from app.infrastructure.speech_presentation.supervisor import (
    PresentationWorkerRegistration,
    SpeechPresentationWorkerSupervisor,
)
from tests.composition.test_system_cognition_configuration import parameters
from tests.config.test_layered import configured_root, edit
from tests.helpers.speech_production import production_sources


class ExternalPorts:
    """本番policyを作らず、外部I/Oと観測境界だけを隔離する。"""

    def __init__(self) -> None:
        self.requests: list[SpeechDeploymentRequest] = []
        self.released = 0
        self.changed: Path | None = None
        self.entered = asyncio.Event()
        self.wait = False

    async def __call__(self, request: SpeechDeploymentRequest) -> SpeechProductionPorts:
        self.requests.append(request)
        self.entered.set()
        if self.wait:
            await asyncio.Event().wait()
        if self.changed is not None:
            edit(self.changed, ("runtime", "queue_capacity"), 5)
        return SpeechProductionPorts(
            request.publication,
            request.publication.roles(),
            UnavailableLLMRolePort(request.provider_roles),
            self,
            self,
            self,
            self,
            SpeechPresentationWorkerSupervisor(
                PresentationWorkerRegistration(
                    "isolated-display", "tests.helpers.speech_path_worker", "build", {}
                )
            ),
            self.readers,
            self.notification,
            self.release,
        )

    async def release(self) -> None:
        self.released += 1

    def readers(self, cognition: Any, reference: Any) -> CoreSpeechContextReaders:
        return CoreSpeechContextReaders(
            self.unused, self.unused, self.sync_unused, self.unused, self.unused
        )

    def notification(self, *args: Any) -> Any:
        raise AssertionError("構築中に提示しない")

    async def unused(self, *args: Any) -> Any:
        raise AssertionError("構築中に外部I/Oを行わない")

    def sync_unused(self, *args: Any) -> Any:
        raise AssertionError("構築中に外部I/Oを行わない")

    async def current_revisions(self, snapshot: Any) -> Any:
        return snapshot.revisions

    async def current_state(self, snapshot: Any) -> Any:
        raise AssertionError("構築中に意味を生成しない")

    async def discard(self, request: Any) -> None:
        raise AssertionError("構築中にartifactはない")


def dependencies() -> dict[str, Any]:
    character = load_character_definition_yaml(
        Path("resources/character_definitions/v2/yura.yaml").read_bytes()
    )
    subject = RuntimeSubjectIdentity(
        character.character_id,
        character.character_id,
        character.schema_version,
        character.definition_revision,
    )
    return dict(
        run=S2RunIdentity("a" * 40, "epoch", "run"),
        semantic_owner=build_speech_semantics_policy_owner_v1(
            runtime_subject_identity=subject, bounds_policy=BOUNDS
        ),
        memory=production_sources()._memory,
    )


@pytest.mark.asyncio
async def test_files_to_real_s2_snapshot_same_owner_and_cleanup(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    ports = ExternalPorts()
    args = dependencies()
    source = create_speech_deployment(
        root, **args, registry=SpeechDeploymentRegistry({"isolated": ports})
    )
    assert source is not None
    app = await bootstrap.build_s2_production_core(**parameters(), speech=source.inputs)
    assert app.core.cognition is not None and app.core.cognition.speech is not None
    assert app.cognition.speech is not None
    assert app.cognition.speech.evidence.owner is args["semantic_owner"]
    pipeline = app.core.cognition.speech.pipeline
    assert pipeline.runtime.operational_policy == source.inputs.publication.runtime
    snapshot = app.composition_snapshot.component_bindings[0].speech
    assert snapshot is not None
    assert snapshot.config_revision == source.inputs.publication.config_revision
    assert snapshot.binding_id == source.inputs.publication.binding_id
    assert snapshot.binding_generation == 1
    assert snapshot.execution_policies == tuple(
        (
            r.role_id,
            r.default_execution_policy.policy_id,
            r.default_execution_policy.policy_revision,
        )
        for r in source.inputs.publication.roles()
    )
    serialized = json.dumps(asdict(app.composition_snapshot), default=str)
    assert str(root) not in serialized and "external-test-model" not in serialized
    await app.start()
    await app.stop()
    await app.stop()
    assert ports.released == 1
    assert len(ports.requests) == 1


def test_owner_registrations_and_explicit_voice_survive_configuration(tmp_path: Path) -> None:
    root = configured_root(tmp_path, available=True)
    deployment = root / "profiles/deployment/isolated.yaml"
    edit(
        deployment,
        ("tts",),
        {
            "availability": "available",
            "provider": "external-provider",
            "voice": "external-voice",
            "locale": "ja-JP",
        },
    )
    source = create_speech_deployment(
        root, **dependencies(), registry=SpeechDeploymentRegistry({"isolated": ExternalPorts()})
    )
    assert source is not None
    request = source.request
    assert request.voice is not None
    assert request.voice.provider_voice_ref == "external-voice"
    configs = {c.role_id: c for c in request.role_configs}
    assert configs["speech_semantics"].instructions == speech_semantics_instructions()
    assert configs["speech_semantics"].output_schema_id == PROVIDER_OUTPUT_SCHEMA
    assert request.provider_roles[0].output_schema_id == PROVIDER_OUTPUT_SCHEMA
    for config in configs.values():
        Draft202012Validator.check_schema(dict(config.output_json_schema))
        assert all(p.model == "external-test-model" for p in config.model_policies.values())
    assert "external-voice" not in repr(request)


@pytest.mark.asyncio
async def test_port_wrapper_is_owner_decoder_and_acquisition_once(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    external = ExternalPorts()
    source = create_speech_deployment(
        root, **dependencies(), registry=SpeechDeploymentRegistry({"isolated": external})
    )
    assert source is not None
    p = source.inputs.publication
    acquired = await source.inputs.acquire(p, p.roles())
    assert isinstance(acquired.llm, SpeechSemanticsProviderPort)
    with pytest.raises(ConfigurationError):
        await source.inputs.acquire(p, p.roles())
    await acquired.release()
    assert external.released == 1


@pytest.mark.asyncio
async def test_change_during_acquisition_releases_without_runtime_adoption(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    external = ExternalPorts()
    external.changed = root / "profiles/speech/conservative.yaml"
    source = create_speech_deployment(
        root, **dependencies(), registry=SpeechDeploymentRegistry({"isolated": external})
    )
    assert source is not None
    p = source.inputs.publication
    with pytest.raises(ConfigurationError):
        await source.inputs.acquire(p, p.roles())
    assert external.released == 1


def test_restart_required_and_new_run_has_new_binding(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    args = dependencies()
    registry = SpeechDeploymentRegistry({"isolated": ExternalPorts()})
    source = create_speech_deployment(root, **args, registry=registry)
    assert source is not None
    old = source.inputs.publication
    edit(root / "profiles/speech/conservative.yaml", ("runtime", "queue_capacity"), 5)
    with pytest.raises(ConfigurationError):
        source.current_publication()
    args["run"] = replace(args["run"], system_run_id="next-run")
    fresh = create_speech_deployment(root, **args, registry=registry)
    assert fresh is not None
    assert fresh.inputs.publication.binding_id != old.binding_id
    assert fresh.inputs.publication.config_revision != old.config_revision
    assert old.runtime.prepared_queue_capacity == 4


def test_missing_registration_and_mapping_limits_fail_closed(tmp_path: Path) -> None:
    root = configured_root(tmp_path, available=True)
    with pytest.raises(ConfigurationError):
        create_speech_deployment(root, **dependencies(), registry=SpeechDeploymentRegistry({}))
    edit(
        root / "profiles/deployment/isolated.yaml",
        ("llm", "roles", "speech_semantics", "max_output_tokens"),
        1,
    )
    with pytest.raises(ConfigurationError):
        create_speech_deployment(
            root, **dependencies(), registry=SpeechDeploymentRegistry({"isolated": ExternalPorts()})
        )


def test_disabled_speech_does_not_acquire_or_require_deployment() -> None:
    external = ExternalPorts()
    result = create_speech_deployment(
        Path("resources/config/v2"),
        **dependencies(),
        registry=SpeechDeploymentRegistry({"isolated": external}),
    )
    assert result is None and not external.requests


@pytest.mark.asyncio
async def test_cancel_during_external_acquisition_is_not_success(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    external = ExternalPorts()
    external.wait = True
    source = create_speech_deployment(
        root, **dependencies(), registry=SpeechDeploymentRegistry({"isolated": external})
    )
    assert source is not None
    p = source.inputs.publication
    task = asyncio.ensure_future(source.inputs.acquire(p, p.roles()))
    await external.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert external.released == 0  # 返却前の所有権は取得側に留まる。


@pytest.mark.asyncio
async def test_external_error_does_not_leak_private_details(tmp_path: Path) -> None:
    root = configured_root(tmp_path)

    async def fail(request: SpeechDeploymentRequest) -> SpeechProductionPorts:
        raise RuntimeError("秘密の接続先とcredential")

    source = create_speech_deployment(
        root, **dependencies(), registry=SpeechDeploymentRegistry({"isolated": fail})
    )
    assert source is not None
    p = source.inputs.publication
    with pytest.raises(ConfigurationError) as error:
        await source.inputs.acquire(p, p.roles())
    assert "秘密" not in str(error.value)


@pytest.mark.asyncio
async def test_bad_publication_reclaims_returned_lease(tmp_path: Path) -> None:
    root = configured_root(tmp_path)
    external = ExternalPorts()

    async def mismatch(request: SpeechDeploymentRequest) -> SpeechProductionPorts:
        ports = await external(request)
        return replace(ports, publication=replace(ports.publication, binding_generation=2))

    source = create_speech_deployment(
        root, **dependencies(), registry=SpeechDeploymentRegistry({"isolated": mismatch})
    )
    assert source is not None
    p = source.inputs.publication
    with pytest.raises(ConfigurationError):
        await source.inputs.acquire(p, p.roles())
    assert external.released == 1


def test_configured_temperature_mapping_and_limit(tmp_path: Path) -> None:
    root = configured_root(tmp_path, available=True)
    profile = root / "profiles/speech/conservative.yaml"
    deployment = root / "profiles/deployment/isolated.yaml"
    edit(profile, ("executions", "speech_semantics", "temperature"), 0.5)
    registry = SpeechDeploymentRegistry({"isolated": ExternalPorts()})
    with pytest.raises(ConfigurationError):
        create_speech_deployment(root, **dependencies(), registry=registry)
    edit(
        deployment,
        ("llm", "roles", "speech_semantics", "temperature_range"),
        {"minimum": 0.0, "maximum": 2.0},
    )
    source = create_speech_deployment(root, **dependencies(), registry=registry)
    assert source is not None
    policy = next(iter(source.request.role_configs[0].model_policies.values()))
    assert policy.temperature_mapping is not None
    assert policy.temperature_mapping.resolve(0.5) == 1.0
