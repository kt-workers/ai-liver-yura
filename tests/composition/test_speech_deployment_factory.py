"""#709 の本番Speech deployment factoryに固有の資源境界を確認する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.composition.cognition import CoreCognitionDelivery
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.presentation_notification import CoreSpeechProductionOwnerConnection
from app.composition.speech import CoreSpeechContextReaders, SpeechOutputPreparationRequest
from app.composition.speech_deployment import production_speech_deployment_registry
from app.composition.speech_deployment_factory import (
    ProductionSpeechDeploymentPortFactory,
    SpeechDeploymentFactoryError,
    _BoundOwnerConnection,
    speech_tts_request_id,
)
from app.config.layered import ConfigurationError
from app.domain.speech_runtime.contracts import SpeechPresentationMode
from tests.composition.test_speech_parallel_preparation import normalizer
from tests.helpers.speech_path import build_speech_path


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
