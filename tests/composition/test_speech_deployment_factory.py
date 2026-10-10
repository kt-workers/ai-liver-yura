"""#709 の本番Speech deployment factoryに固有の資源境界を確認する。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app import bootstrap
from app.adapters.llm.s2_production import create_s2_provider_lease
from app.adapters.tts.production import TTSProductionConnection, TTSProviderRegistry
from app.adapters.tts.provider import TTSProviderClient
from app.composition.cognition import CoreCognitionDelivery
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.presentation_notification import CoreSpeechProductionOwnerConnection
from app.composition.s2_provider import S2ProviderLease
from app.composition.speech import CoreSpeechContextReaders, SpeechOutputPreparationRequest
from app.composition.speech_deployment import (
    SpeechDeploymentRequest,
    create_speech_deployment,
    production_speech_deployment_registry,
)
from app.composition.speech_deployment_factory import (
    ProductionSpeechDeploymentPortFactory,
    SpeechDeploymentFactoryError,
    SpeechDeploymentOwnerConnections,
    _BoundOwnerConnection,
    speech_tts_request_id,
)
from app.config.layered import ConfigurationError, load_user_configuration
from app.domain.speech_runtime.contracts import SpeechPresentationMode
from app.infrastructure.speech_presentation.production import (
    PresentationProductionRegistration,
    PresentationWorkerRegistry,
)
from tests.adapters.tts.test_production import FakeTTSClient, capability, registration
from tests.adapters.tts.test_provider import _policy
from tests.composition.test_speech_deployment import dependencies
from tests.composition.test_speech_parallel_preparation import normalizer
from tests.composition.test_system_cognition_configuration import parameters
from tests.config.test_layered import configured_root
from tests.helpers.speech_path import build_speech_path
from tests.infrastructure.speech_presentation.test_production import worker


class _Lease:
    def __init__(
        self,
        events: list[str],
        name: str,
        *,
        fail: bool = False,
        cancel: bool = False,
        started: asyncio.Event | None = None,
        proceed: asyncio.Event | None = None,
    ) -> None:
        self._events, self._name, self._fail, self._cancel = events, name, fail, cancel
        self._started, self._proceed = started, proceed

    async def close(self) -> None:
        self._events.append(self._name)
        if self._started is not None:
            self._started.set()
        if self._proceed is not None:
            await self._proceed.wait()
        if self._cancel:
            raise asyncio.CancelledError
        if self._fail:
            raise RuntimeError("非公開の失敗")


class _Provider:
    def __init__(self, events: list[str], *, fail: bool = False, cancel: bool = False) -> None:
        self._events, self._fail, self._cancel = events, fail, cancel

    async def release(self) -> None:
        self._events.append("provider.release")
        if self._cancel:
            raise asyncio.CancelledError
        if self._fail:
            raise RuntimeError("非公開の失敗")


@dataclass(frozen=True)
class _RequestIdentity:
    candidate_id: str
    candidate_generation: int
    performance_generation: int


@dataclass(frozen=True)
class _MappingIdentity:
    mapping_id: str
    mapping_revision: int


@dataclass(frozen=True)
class _ConnectionIdentity:
    mapping: _MappingIdentity


@pytest.mark.asyncio
async def test_partial_acquisition_cleanup_is_reverse_order() -> None:
    events: list[str] = []
    await ProductionSpeechDeploymentPortFactory._cleanup(
        _Provider(events),
        _Lease(events, "tts.close"),
        _Lease(events, "presentation.close"),
    )
    assert events == ["presentation.close", "tts.close", "provider.release"]


@pytest.mark.asyncio
async def test_cleanup_failure_never_becomes_success() -> None:
    with pytest.raises(SpeechDeploymentFactoryError, match="回収"):
        await ProductionSpeechDeploymentPortFactory._cleanup(
            _Provider([]),
            _Lease([], "tts.close", fail=True),
            None,
        )


@pytest.mark.asyncio
async def test_cancelled_child_cleanup_still_reclaims_remaining_leases() -> None:
    events: list[str] = []
    with pytest.raises(asyncio.CancelledError):
        await ProductionSpeechDeploymentPortFactory._cleanup(
            _Provider(events),
            _Lease(events, "tts.close"),
            _Lease(events, "presentation.close", cancel=True),
        )
    assert events == ["presentation.close", "tts.close", "provider.release"]


@pytest.mark.asyncio
async def test_mixed_child_failure_and_cancellation_reclaims_every_lease() -> None:
    events: list[str] = []
    with pytest.raises(asyncio.CancelledError):
        await ProductionSpeechDeploymentPortFactory._cleanup(
            _Provider(events),
            _Lease(events, "tts.close", fail=True),
            _Lease(events, "presentation.close", cancel=True),
        )
    assert events == ["presentation.close", "tts.close", "provider.release"]


@pytest.mark.asyncio
async def test_caller_cancellation_waits_for_all_cleanup() -> None:
    events: list[str] = []
    started, proceed = asyncio.Event(), asyncio.Event()
    closing = asyncio.create_task(
        ProductionSpeechDeploymentPortFactory._cleanup(
            _Provider(events),
            _Lease(events, "tts.close"),
            _Lease(events, "presentation.close", started=started, proceed=proceed),
        )
    )
    await started.wait()
    closing.cancel()
    assert not closing.done()
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert events == ["presentation.close", "tts.close", "provider.release"]


@pytest.mark.asyncio
async def test_construction_failure_is_preserved_when_cleanup_also_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    construction_failure = RuntimeError("構築失敗")

    async def release() -> None:
        events.append("provider.release")
        raise RuntimeError("非公開のprovider回収失敗")

    async def provider(*_: object) -> S2ProviderLease:
        port: Any = object()
        return S2ProviderLease(port, (), "unconfigured", release)

    class _Presentation:
        async def acquire(self, _: object) -> None:
            raise construction_failure

    class _Bindings:
        def factory_inputs(
            self,
        ) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...], str]:
            return (), (), (), "unconfigured"

    class _Publication:
        output_modes = (SpeechPresentationMode.TEXT_ONLY,)
        presentation = SimpleNamespace(
            identity="presentation", revision=1, availability="available"
        )

        @staticmethod
        def roles() -> tuple[object, ...]:
            return ()

    request = object.__new__(SpeechDeploymentRequest)
    object.__setattr__(request, "publication", _Publication())
    object.__setattr__(request, "provider_bindings", _Bindings())
    object.__setattr__(request, "voice", None)
    factory = object.__new__(ProductionSpeechDeploymentPortFactory)
    object.__setattr__(
        factory,
        "_connections",
        cast(Any, SimpleNamespace(provider_factory=provider, presentation=_Presentation())),
    )

    with caplog.at_level(logging.WARNING, logger="app.composition.speech_deployment_factory"):
        with pytest.raises(RuntimeError) as raised:
            await factory(request)

    assert raised.value is construction_failure
    assert events == ["provider.release"]
    assert caplog.messages == ["Speech本番構築失敗後のlease回収に失敗しました"]


def test_tts_request_id_uses_exact_public_identity_material() -> None:
    request = _RequestIdentity("candidate", 2, 3)
    connection = _ConnectionIdentity(_MappingIdentity("mapping", 4))
    first = speech_tts_request_id(request, connection, "voice", 5)
    second = speech_tts_request_id(request, connection, "voice", 5)
    changed = speech_tts_request_id(request, connection, "voice", 6)
    assert first == second
    assert first.startswith("tts-") and len(first) == 68
    assert changed != first


def test_registry_rejects_untrusted_factory_bundle() -> None:
    with pytest.raises(ConfigurationError):
        production_speech_deployment_registry({"production": object()})


@pytest.mark.asyncio
async def test_owner_connection_is_fixed_once_per_configuration_handle() -> None:
    value = await build_speech_path()
    other = await build_speech_path()
    try:
        owner = CoreSpeechProductionOwnerConnection(
            value.authority, value.attention, value.reference, normalizer(), value.cognition
        )
        later = CoreSpeechProductionOwnerConnection(
            other.authority, other.attention, other.reference, normalizer(), other.cognition
        )
        resolutions: list[tuple[CoreCognitionDelivery, CoreInputReferenceContextBinding]] = []

        def resolver(
            cognition: CoreCognitionDelivery, reference: CoreInputReferenceContextBinding
        ) -> CoreSpeechProductionOwnerConnection:
            resolutions.append((cognition, reference))
            return owner if len(resolutions) == 1 else later

        def readers(
            cognition: CoreCognitionDelivery, reference: CoreInputReferenceContextBinding
        ) -> CoreSpeechContextReaders:
            assert cognition is value.cognition and reference is value.reference
            result = value.pipeline.readers
            assert isinstance(result, CoreSpeechContextReaders)
            return result

        async def output(
            _: SpeechOutputPreparationRequest,
        ) -> tuple[SpeechPresentationMode, str | None]:
            raise AssertionError("同期結合でTTSを開始しない")

        binding = _BoundOwnerConnection(resolver, readers, output)
        assert binding.readers(value.cognition, value.reference) is not None
        first = binding.notification(
            value.cognition, value.reference, value.work, value.decision, "a"
        )
        second = binding.notification(
            value.cognition, value.reference, value.work, value.decision, "b"
        )
        assert len(resolutions) == 1
        assert first.normalizer is owner.normalizer is second.normalizer
        with pytest.raises(SpeechDeploymentFactoryError, match="一度だけ"):
            binding.readers(value.cognition, value.reference)
        with pytest.raises(SpeechDeploymentFactoryError, match="未結合又は不一致"):
            binding.notification(
                other.cognition, other.reference, other.work, other.decision, "other"
            )
    finally:
        await value.close()
        await other.close()


@pytest.mark.asyncio
async def test_unbound_owner_connection_rejects_notification() -> None:
    value = await build_speech_path()
    try:
        owner = CoreSpeechProductionOwnerConnection(
            value.authority, value.attention, value.reference, normalizer(), value.cognition
        )

        async def output(
            _: SpeechOutputPreparationRequest,
        ) -> tuple[SpeechPresentationMode, str | None]:
            raise AssertionError("同期結合でTTSを開始しない")

        binding = _BoundOwnerConnection(
            lambda cognition, reference: owner,
            lambda cognition, reference: value.pipeline.readers,
            output,
        )
        with pytest.raises(SpeechDeploymentFactoryError, match="未結合"):
            binding.notification(value.cognition, value.reference, value.work, value.decision, "a")
    finally:
        await value.close()


@pytest.mark.asyncio
async def test_returned_release_joins_repeated_calls_once() -> None:
    events: list[str] = []
    release = ProductionSpeechDeploymentPortFactory._release(
        _Provider(events),
        _Lease(events, "tts.close"),
        _Lease(events, "presentation.close"),
    )
    await asyncio.gather(release(), release(), release())
    assert events == ["presentation.close", "tts.close", "provider.release"]


@pytest.mark.asyncio
@pytest.mark.parametrize("available", (False, True))
async def test_registered_production_factory_reaches_s2_with_separate_role_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    """登録済みfactoryからS2まで、Provider用とDomain用のRoleを混同しない。"""
    import openai

    path = await build_speech_path()
    root = configured_root(tmp_path, available=available)
    configuration = load_user_configuration(root)
    assert configuration.deployment is not None
    calls: list[tuple[object, object, object, str]] = []
    discarded: list[str] = []
    released: list[TTSProviderClient] = []
    policies = _policy()

    async def provider(roles: Any, configs: Any, bindings: Any, mode: str) -> Any:
        calls.append((roles, configs, bindings, mode))
        return await create_s2_provider_lease(roles, configs, bindings, mode)

    class FakeAsyncOpenAI:
        async def close(self) -> None:
            return None

        def __init__(self, *, api_key: str) -> None:
            self.responses = object()

    if available:
        monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
        monkeypatch.setenv("YURA_OPENAI_API_KEY", "test-only-key")
    else:
        monkeypatch.delenv("YURA_OPENAI_API_KEY", raising=False)

    try:
        connection = SpeechDeploymentOwnerConnections(
            provider,
            TTSProductionConnection(
                TTSProviderRegistry((registration(FakeTTSClient(), discarded, released),)),
                replace(capability(provider_id="fake", revision=1), provider_revision=1),
                policies.mapping,
                policies.operational,
                policies.retry,
                (),
                1,
                1,
            ),
            PresentationWorkerRegistry(
                (
                    PresentationProductionRegistration(
                        configuration.deployment.identity + ".presentation",
                        configuration.deployment.revision,
                        worker(),
                    ),
                )
            ),
            lambda cognition, reference: CoreSpeechProductionOwnerConnection(
                reference.activities, cognition.attention_owner, reference, normalizer(), cognition
            ),
            lambda cognition, reference: path.pipeline.readers,
            path.pipeline.semantics._live_state,
            path.pipeline.character._live_state,
            path.pipeline.verifier._live_state,
        )
        registry = production_speech_deployment_registry({"isolated": connection})
        source = create_speech_deployment(
            root, **dependencies(), registry=registry
        )
        assert source is not None
        app = await bootstrap.build_s2_production_core(**parameters(), speech=source.inputs)
        provider_roles, configs, bindings, mode = source.request.provider_bindings.factory_inputs()
        assert calls == [(provider_roles, configs, bindings, mode)]
        assert tuple(role.role_id for role in provider_roles) == tuple(
            role.role_id for role in source.request.publication.roles()
        )
        assert app.core.cognition is not None and app.core.cognition.speech is not None
        assert (
            app.core.cognition.speech.pipeline.output_modes
            == source.request.publication.output_modes
        )
        await asyncio.gather(app.stop(), app.stop())
        assert discarded == [] and released == []
    finally:
        await path.close()
