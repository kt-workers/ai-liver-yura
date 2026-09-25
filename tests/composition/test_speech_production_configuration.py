"""明示したOwner構成の接続・由来・資源移管をSystem入口で確認する。"""

import asyncio
import json
from dataclasses import asdict, replace
from typing import Any, cast

import pytest

from app import bootstrap
from app.adapters.llm.production import UnavailableLLMRolePort
from app.composition import speech_production_configuration as speech
from app.composition.speech import CoreSpeechContextReaders
from app.composition.speech_semantics_policy import build_speech_semantics_policy_owner_v1
from app.config.s2_contracts import S2ConfigurationError
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity
from app.domain.speech_performance.policy import yura_revision_1_policy
from app.domain.speech_runtime.contracts import SpeechPresentationMode, TTSPreparationMode
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.infrastructure.speech_presentation.supervisor import (
    PresentationWorkerRegistration,
    SpeechPresentationWorkerSupervisor,
)
from tests.composition.test_system_cognition_configuration import parameters
from tests.domain.character_language.test_character_language import policy as character_policy
from tests.domain.semantic_verification.test_semantic_verification import verification_policy
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_semantics.test_speech_semantics import policy as semantics_policy
from tests.helpers.speech_production import production_sources


class Deployment:
    """試験でだけ注入する提供元。factoryへの既定値や本番fallbackにはしない。"""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.owner = build_speech_semantics_policy_owner_v1(
            runtime_subject_identity=RuntimeSubjectIdentity("yura", "yura", 1, 1),
            bounds_policy=BOUNDS,
        )
        self.publication = speech.SpeechProductionPublication(
            "deployment.speech",
            "speech.config",
            1,
            "speech.binding",
            1,
            1,
            "yura",
            1,
            replace(semantics_policy(), meaning_policy=self.owner.publication().value.meaning),
            character_policy(),
            verification_policy(),
            yura_revision_1_policy(),
            runtime_policy(),
            speech.SpeechBindingReference("llm.binding", 1, "unavailable"),
            speech.SpeechBindingReference("tts.binding", 1, "unavailable"),
            speech.SpeechBindingReference("presentation.binding", 1, "available"),
            (SpeechPresentationMode.TEXT_ONLY,),
            TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE,
            SpeechCandidatePriority.FOREGROUND,
            "expiry",
        )
        self.memory = production_sources()._memory
        self.acquire_error = False
        self.release_error = False
        self.stale_after_acquire = False
        self.bad_roles = False
        self.build_error = False

    def current(self) -> speech.SpeechProductionPublication:
        return self.publication

    async def release(self) -> None:
        self.events.append("release")
        if self.release_error:
            raise RuntimeError("非公開の提供先エラー")

    async def acquire(self, publication: Any, roles: Any) -> speech.SpeechProductionPorts:
        self.events.append("acquire")
        if self.acquire_error:
            raise RuntimeError("非公開の提供先エラー")
        if self.stale_after_acquire:
            self.publication = replace(publication, binding_generation=2)
        return speech.SpeechProductionPorts(
            publication,
            () if self.bad_roles else roles,
            UnavailableLLMRolePort(roles),
            self,
            self,
            self,
            self,
            SpeechPresentationWorkerSupervisor(
                PresentationWorkerRegistration(
                    "text", "tests.helpers.speech_path_worker", "build", {}
                )
            ),
            self.readers,
            self.notification,
            self.release,
        )

    def readers(self, cognition: Any, reference: Any) -> CoreSpeechContextReaders:
        self.events.append("build")
        if self.build_error:
            raise RuntimeError("非公開の接続エラー")
        return CoreSpeechContextReaders(
            self.unused, self.unused, self.sync_unused, self.unused, self.unused
        )

    def notification(self, *args: Any) -> Any:
        raise AssertionError("構築だけで通知しない")

    async def unused(self, *args: Any) -> Any:
        raise AssertionError("構築だけで外部処理しない")

    def sync_unused(self, *args: Any) -> Any:
        raise AssertionError("構築だけで外部処理しない")

    async def current_revisions(self, snapshot: Any) -> Any:
        return snapshot.revisions

    async def current_state(self, snapshot: Any) -> Any:
        raise AssertionError("構築だけで意味判断しない")

    async def discard(self, request: Any) -> None:
        self.events.append("discard")

    def inputs(self) -> speech.SpeechProductionInputs:
        return speech.SpeechProductionInputs(
            self.publication,
            self.current,
            self.owner,
            self.memory,
            self.acquire,
        )


@pytest.mark.asyncio
async def test_production_factory_shared_binding_snapshot_and_single_cleanup(
    monkeypatch: Any,
) -> None:
    d = Deployment()
    app = await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert app.core.cognition is not None
    assert app.cognition.speech is not None
    delivery = app.core.cognition.speech
    assert delivery is not None
    pipeline = delivery.pipeline
    assert (
        pipeline.context is cast(Any, app.cognition.speech.build).__self__._semantic.context_builder
    )
    assert app.cognition.speech.evidence.owner is d.owner
    assert app.cognition.speech.evidence.sources._goals is app.core.goals
    assert app.cognition.speech.evidence.sources._execution is app.core.activities
    assert app.cognition.speech.evidence.sources._memory is d.memory
    p = app.composition_snapshot.component_bindings[0].speech
    assert p is not None
    meaning = d.owner.publication().value.meaning
    assert meaning is not None
    assert p.binding_generation == 1
    assert p.runtime_policy_id == pipeline.runtime.operational_policy.policy_id
    assert p.semantic_policy_id == meaning.policy_id
    assert p.performance_policy_id == d.publication.performance.policy_id
    assert p.provider == d.publication.provider
    assert p.tts == d.publication.tts
    assert p.presentation == d.publication.presentation
    assert p.runtime_epoch == app.composition_snapshot.runtime_epoch
    assert p.system_run_id == app.composition_snapshot.system_run_id
    assert p.character_id == app.composition_snapshot.character_id
    assert p.execution_policies == tuple(
        (
            r.role_id,
            r.default_execution_policy.policy_id,
            r.default_execution_policy.policy_revision,
        )
        for r in d.publication.roles()
    )
    assert "_memory" not in json.dumps(asdict(app.composition_snapshot), default=str)
    with pytest.raises(S2ConfigurationError):
        app.cognition.speech.compose(app.core.cognition, app.core.input_context)
    calls: list[str] = []
    close = pipeline.close

    async def tracked() -> None:
        calls.append("pipeline")
        await close()

    monkeypatch.setattr(pipeline, "close", tracked)
    await app.start()
    await asyncio.gather(app.stop(), app.stop())
    assert calls == ["pipeline"]
    assert d.events == ["acquire", "build", "release"]
    assert pipeline.pending_preparation_tasks == 0
    assert d.owner.publication()
    assert cast(Any, d.memory).owner is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["stale_after_acquire", "bad_roles", "build_error"])
async def test_partial_failure_releases_once(fault: str) -> None:
    d = Deployment()
    setattr(d, fault, True)
    with pytest.raises(S2ConfigurationError) as error:
        await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert "非公開" not in str(error.value)
    assert d.events.count("release") == 1
    assert d.owner.publication()


@pytest.mark.asyncio
async def test_changed_generation_before_acquire_rejected() -> None:
    d = Deployment()
    inputs = d.inputs()
    d.publication = replace(d.publication, binding_generation=2)
    with pytest.raises(S2ConfigurationError):
        await bootstrap.build_s2_production_core(**parameters(), speech=inputs)
    assert d.events == []


@pytest.mark.asyncio
async def test_speech_not_configured_keeps_cognition_only() -> None:
    app = await bootstrap.build_s2_production_core(**parameters())
    assert app.composition_snapshot.component_bindings[0].speech is None
    assert app.cognition.speech is None
    await app.stop()


@pytest.mark.parametrize(
    "field,value",
    [
        ("binding_generation", 0),
        ("config_revision", True),
        ("source_id", "/private/secret"),
        ("output_modes", ()),
        ("tts_mode", TTSPreparationMode.DISABLED),
    ],
)
def test_invalid_publication_rejected(field: str, value: Any) -> None:
    d = Deployment()
    with pytest.raises(S2ConfigurationError):
        replace(d.publication, **{field: value})


@pytest.mark.asyncio
async def test_wrong_character_and_missing_input_fail_closed() -> None:
    d = Deployment()
    d.publication = replace(d.publication, character_id="other")
    with pytest.raises(S2ConfigurationError):
        await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    with pytest.raises(S2ConfigurationError):
        await bootstrap.build_s2_production_core(**parameters(), speech=cast(Any, object()))
    assert d.events == []


@pytest.mark.asyncio
async def test_semantic_currentness_change_after_registration_reclaims_pipeline(
    monkeypatch: Any,
) -> None:
    d = Deployment()
    original = bootstrap._compose_core
    pipelines: list[Any] = []

    def compose(*args: Any, **kwargs: Any) -> Any:
        core = original(*args, **kwargs)
        assert core.cognition is not None and core.cognition.speech is not None
        pipelines.append(core.cognition.speech.pipeline)
        d.publication = replace(d.publication, binding_revision=2, binding_generation=2)
        return core

    monkeypatch.setattr(bootstrap, "_compose_core", compose)
    with pytest.raises(S2ConfigurationError, match="INITIALIZATION_FAILED"):
        await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert d.events.count("release") == 1
    assert pipelines[0]._closed
    assert pipelines[0].pending_preparation_tasks == 0


@pytest.mark.asyncio
async def test_compose_failure_after_pipeline_creation_reclaims_handle(monkeypatch: Any) -> None:
    d = Deployment()
    original = bootstrap._compose_core
    pipelines: list[Any] = []

    def compose(*args: Any, **kwargs: Any) -> Any:
        core = original(*args, **kwargs)
        assert core.cognition is not None and core.cognition.speech is not None
        pipelines.append(core.cognition.speech.pipeline)
        raise RuntimeError("部分構築失敗")

    monkeypatch.setattr(bootstrap, "_compose_core", compose)
    with pytest.raises(S2ConfigurationError):
        await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert pipelines[0]._closed
    assert pipelines[0].pending_preparation_tasks == 0
    assert d.events.count("release") == 1


@pytest.mark.asyncio
async def test_cancelled_stop_waits_for_release_then_reraises(monkeypatch: Any) -> None:
    d = Deployment()
    started, finish = asyncio.Event(), asyncio.Event()

    async def release() -> None:
        started.set()
        await finish.wait()
        d.events.append("release")

    monkeypatch.setattr(d, "release", release)
    app = await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    stop = asyncio.create_task(app.stop())
    await started.wait()
    stop.cancel()
    await asyncio.sleep(0)
    assert not stop.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await stop
    await app.stop()
    assert d.events.count("release") == 1
    assert app.core.cognition is not None and app.core.cognition.speech is not None
    assert app.core.cognition.speech.pipeline.pending_preparation_tasks == 0


@pytest.mark.asyncio
async def test_cleanup_failure_still_releases_cognition_provider(monkeypatch: Any) -> None:
    from tests.composition.test_system_cognition_configuration import unavailable_lease

    d = Deployment()
    d.release_error = True
    order: list[str] = []

    async def provider(*args: Any) -> Any:
        lease = await unavailable_lease(*args)

        async def release() -> None:
            order.append("provider")

        return replace(lease, release_owned=release)

    params = parameters()
    params["provider_factory"] = provider
    app = await bootstrap.build_s2_production_core(**params, speech=d.inputs())
    with pytest.raises(S2ConfigurationError, match="INITIALIZATION_FAILED"):
        await app.stop()
    assert d.events.count("release") == 1
    assert order == ["provider"]
    with pytest.raises(S2ConfigurationError):
        await app.stop()
    assert order == ["provider"]


@pytest.mark.asyncio
async def test_cancel_during_partial_build_preserves_cancel_and_reclaims(monkeypatch: Any) -> None:
    d = Deployment()
    d.release_error = True

    def readers(*args: Any) -> Any:
        raise asyncio.CancelledError

    monkeypatch.setattr(d, "readers", readers)
    with pytest.raises(asyncio.CancelledError):
        await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert d.events.count("release") == 1


@pytest.mark.asyncio
async def test_semantic_owner_changed_while_acquiring_rejected(monkeypatch: Any) -> None:
    d = Deployment()
    acquire = d.acquire

    async def changed(*args: Any) -> Any:
        ports = await acquire(*args)
        values = d.owner.publication().value
        assert values.meaning is not None
        d.owner.update(
            replace(
                values,
                meaning=replace(
                    values.meaning,
                    revision=2,
                    communicative_goal_catalog=replace(
                        values.meaning.communicative_goal_catalog, policy_revision=2
                    ),
                ),
            )
        )
        return ports

    monkeypatch.setattr(d, "acquire", changed)
    with pytest.raises(S2ConfigurationError):
        await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert d.events.count("release") == 1


def test_production_factory_has_no_test_dependency() -> None:
    import ast
    from pathlib import Path

    tree = ast.parse(Path(speech.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("tests")
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("tests") for alias in node.names)


@pytest.mark.asyncio
async def test_system_stop_reaps_registered_speech_work_and_keeps_borrowed_owner(
    monkeypatch: Any,
) -> None:
    from app.domain.speech_runtime.tasks import CandidateTaskKey

    d = Deployment()

    async def forbidden_close() -> None:
        raise AssertionError("借用Memoryを閉じてはいけない")

    monkeypatch.setattr(d.memory, "close", forbidden_close)
    app = await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert app.core.cognition is not None and app.core.cognition.speech is not None
    pipeline = app.core.cognition.speech.pipeline
    started = asyncio.Event()
    reclaimed = asyncio.Event()

    async def work() -> object:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            reclaimed.set()
        return None

    task = pipeline._tasks.start(CandidateTaskKey("candidate", 1, "output"), work())
    await started.wait()
    await app.stop()
    assert reclaimed.is_set()
    assert task.done()
    assert pipeline.pending_preparation_tasks == 0
    assert d.events.count("release") == 1


@pytest.mark.asyncio
async def test_pipeline_cleanup_failure_does_not_skip_runtime_or_lease(monkeypatch: Any) -> None:
    d = Deployment()
    app = await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert app.core.cognition is not None and app.core.cognition.speech is not None
    delivery = app.core.cognition.speech
    calls: list[str] = []
    original_shutdown = delivery.shutdown.close

    async def fail() -> None:
        calls.append("pipeline")
        raise RuntimeError("回収失敗")

    async def shutdown() -> tuple[str, ...]:
        calls.append("runtime")
        return await original_shutdown()

    monkeypatch.setattr(delivery.pipeline, "close", fail)
    monkeypatch.setattr(delivery.shutdown, "close", shutdown)
    with pytest.raises(S2ConfigurationError):
        await app.stop()
    assert calls == ["pipeline", "runtime"]
    assert d.events.count("release") == 1


@pytest.mark.asyncio
async def test_lease_publication_mismatch_releases_before_reject(monkeypatch: Any) -> None:
    d = Deployment()
    original = d.acquire

    async def acquire(*args: Any) -> speech.SpeechProductionPorts:
        ports = await original(*args)
        return replace(ports, publication=replace(ports.publication, binding_revision=2))

    monkeypatch.setattr(d, "acquire", acquire)
    with pytest.raises(S2ConfigurationError):
        await bootstrap.build_s2_production_core(**parameters(), speech=d.inputs())
    assert d.events == ["acquire", "release"]
