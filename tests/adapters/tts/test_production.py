from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast

import pytest

from app.adapters.tts.contracts import PronunciationOverrideView, TTSCapabilityView, TTSVoiceBinding
from app.adapters.tts.d10_provider import TTSProviderAdapter
from app.adapters.tts.production import (
    TTSProductionCleanupError,
    TTSProductionConfigurationError,
    TTSProductionConnection,
    TTSProductionLease,
    TTSProviderLease,
    TTSProviderRegistration,
    TTSProviderRegistry,
)
from app.adapters.tts.provider import (
    ProviderSynthesisInput,
    TTSProviderClient,
    TTSProviderResponse,
)
from app.domain.speech_runtime.discard import (
    PreparedAudioDiscardReason,
    PreparedAudioDiscardRequest,
)
from tests.adapters.tts.test_provider import FakeTTS, _policy, _request, _response


class FakeTTSClient:
    async def synthesize(
        self,
        voice_ref: str,
        texts: tuple[str, ...],
        provider_input: ProviderSynthesisInput,
    ) -> TTSProviderResponse:
        raise AssertionError("この試験は外部TTSを呼び出しません")


class _RecordingProductionAdapter:
    def __init__(
        self,
        order: list[str],
        *,
        entered: asyncio.Event | None = None,
        finish: asyncio.Event | None = None,
        failure: Exception | None = None,
    ) -> None:
        self._order = order
        self._entered = entered
        self._finish = finish
        self._failure = failure

    async def shutdown(self) -> None:
        self._order.append("adapter.shutdown")
        if self._entered is not None:
            self._entered.set()
        if self._finish is not None:
            await self._finish.wait()
        if self._failure is not None:
            raise self._failure


class _RecordingProviderLease:
    def __init__(self, order: list[str]) -> None:
        self.resources = object()
        self._order = order

    async def close(self) -> None:
        self._order.append("provider_lease.close")


def _production_lease(
    adapter: _RecordingProductionAdapter, provider_lease: _RecordingProviderLease
) -> TTSProductionLease:
    return TTSProductionLease(
        cast(TTSProviderAdapter, adapter), cast(TTSProviderLease, provider_lease)
    )


def binding(*, provider_id: str = "provider", revision: int = 1) -> TTSVoiceBinding:
    return TTSVoiceBinding("yura_tts", "yura", provider_id, "voice", revision, "ja_JP", True)


def capability(*, provider_id: str = "provider", revision: int = 1) -> TTSCapabilityView:
    return TTSCapabilityView(
        provider_id,
        7,
        revision,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )


def registration(
    client: FakeTTSClient,
    discarded: list[str],
    released: list[TTSProviderClient],
) -> TTSProviderRegistration:
    async def discard(raw_resource_ref: str) -> None:
        discarded.append(raw_resource_ref)

    async def release(value: TTSProviderClient) -> None:
        released.append(value)

    return TTSProviderRegistration("yura_tts", 1, "provider", 7, lambda: client, discard, release)


@pytest.mark.asyncio
async def test_exact_binding_acquires_client_and_discards_same_artifact_once() -> None:
    client = FakeTTSClient()
    discarded: list[str] = []
    released: list[TTSProviderClient] = []
    lease = await TTSProviderRegistry((registration(client, discarded, released),)).acquire(
        binding(), capability()
    )

    audio_ref = lease.resources.store("artifact", "request", "private_handle")
    request = PreparedAudioDiscardRequest(
        "candidate",
        "utterance",
        "performance",
        audio_ref,
        PreparedAudioDiscardReason.CANDIDATE_STALE,
    )
    await asyncio.gather(lease.resources.discard(request), lease.resources.discard(request))

    assert lease.client is client
    assert lease.resources.resolve(audio_ref) is None
    assert discarded == ["private_handle"]
    assert released == []
    await lease.close()
    await lease.close()
    assert released == [client]


@pytest.mark.asyncio
async def test_missing_or_mismatched_binding_fails_without_provider_fallback() -> None:
    client = FakeTTSClient()
    registry = TTSProviderRegistry((registration(client, [], []),))

    with pytest.raises(TTSProductionConfigurationError, match="登録と一致"):
        await registry.acquire(binding(provider_id="other"), capability(provider_id="other"))
    with pytest.raises(TTSProductionConfigurationError, match="登録と一致"):
        await registry.acquire(binding(), capability(revision=2))


@pytest.mark.asyncio
async def test_close_recovers_undiscarded_artifacts_and_client() -> None:
    client = FakeTTSClient()
    discarded: list[str] = []
    released: list[TTSProviderClient] = []
    lease = await TTSProviderRegistry((registration(client, discarded, released),)).acquire(
        binding(), capability()
    )
    first = lease.resources.store("artifact_one", "request_one", "private_one")
    second = lease.resources.store("artifact_two", "request_two", "private_two")

    await lease.close()

    assert lease.resources.resolve(first) is None
    assert lease.resources.resolve(second) is None
    assert set(discarded) == {"private_one", "private_two"}
    assert released == [client]


@pytest.mark.asyncio
async def test_cancelled_close_waits_for_resource_and_client_recovery() -> None:
    client = FakeTTSClient()
    discarded: list[str] = []
    released: list[TTSProviderClient] = []
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def discard(raw_resource_ref: str) -> None:
        discarded.append(raw_resource_ref)

    async def release(value: TTSProviderClient) -> None:
        entered.set()
        await finish.wait()
        released.append(value)

    item = TTSProviderRegistration("yura_tts", 1, "provider", 7, lambda: client, discard, release)
    lease = await TTSProviderRegistry((item,)).acquire(binding(), capability())
    lease.resources.store("artifact", "request", "private_handle")
    closing = asyncio.create_task(lease.close())
    await entered.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await lease.close()
    assert discarded == ["private_handle"]
    assert released == [client]


@pytest.mark.asyncio
async def test_registered_lease_integrates_with_adapter_and_discards_raw_artifact() -> None:
    policies = _policy(max_attempts=1)
    request = _request(bundle=policies)
    response = _response()
    client = FakeTTS([response])
    discarded: list[str] = []
    released: list[TTSProviderClient] = []

    async def discard(raw_resource_ref: str) -> None:
        discarded.append(raw_resource_ref)

    async def release(value: TTSProviderClient) -> None:
        released.append(value)

    voice = request.voice_binding
    item = TTSProviderRegistration(
        voice.binding_id,
        voice.binding_revision,
        voice.provider_id,
        request.capability.provider_revision,
        lambda: client,
        discard,
        release,
    )
    lease = await TTSProviderRegistry((item,)).acquire(voice, request.capability)
    adapter = TTSProviderAdapter(
        lease.client,
        policies.mapping,
        policies.operational,
        policies.retry,
        resource_store=lease.resources,
    )

    result = await adapter.synthesize(request)

    assert result.artifact is not None
    assert result.artifact.audio_ref != response.raw_audio_ref
    assert response.raw_audio_ref not in repr(result)
    await lease.resources.discard(
        PreparedAudioDiscardRequest(
            request.candidate_id,
            request.utterance.utterance_id,
            request.performance_plan.performance_plan_id,
            result.artifact.audio_ref,
            PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
        )
    )
    assert discarded == [response.raw_audio_ref]
    await lease.close()
    assert released == [client]


@pytest.mark.asyncio
async def test_invalid_client_is_released_exactly_once_before_acquisition_failure() -> None:
    client = FakeTTSClient()
    item = registration(client, [], [])
    with pytest.raises(TTSProductionConfigurationError, match="重複"):
        TTSProviderRegistry((item, item))

    released: list[TTSProviderClient] = []

    async def release(value: TTSProviderClient) -> None:
        released.append(value)

    invalid = TTSProviderRegistration(
        "yura_tts",
        1,
        "provider",
        7,
        lambda: cast(TTSProviderClient, object()),
        item.discard_raw_resource,
        release,
    )
    with pytest.raises(TTSProductionConfigurationError, match="clientが不正"):
        await TTSProviderRegistry((invalid,)).acquire(binding(), capability())
    assert len(released) == 1


@pytest.mark.asyncio
async def test_cancelled_acquisition_waits_for_invalid_client_release() -> None:
    entered = asyncio.Event()
    finish = asyncio.Event()
    released: list[TTSProviderClient] = []

    async def discard(raw_resource_ref: str) -> None:
        raise AssertionError(raw_resource_ref)

    async def release(value: TTSProviderClient) -> None:
        entered.set()
        await finish.wait()
        released.append(value)

    item = TTSProviderRegistration(
        "yura_tts",
        1,
        "provider",
        7,
        lambda: cast(TTSProviderClient, object()),
        discard,
        release,
    )
    acquiring = asyncio.create_task(TTSProviderRegistry((item,)).acquire(binding(), capability()))
    await entered.wait()
    acquiring.cancel()
    await asyncio.sleep(0)
    assert not acquiring.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await acquiring
    assert len(released) == 1


def test_production_connection_rejects_mismatched_generation_and_duplicate_overrides() -> None:
    policies = _policy(max_attempts=1)
    client = FakeTTSClient()
    registry = TTSProviderRegistry((registration(client, [], []),))
    request = _request(bundle=policies)
    with pytest.raises(TTSProductionConfigurationError):
        TTSProductionConnection(
            registry, capability(provider_id="other"), policies.mapping, policies.operational,
            policies.retry, (), 3, 9
        )
    override = PronunciationOverrideView("override", "表層", "ヨミ", "ja_JP", "owner", 1)
    with pytest.raises(TTSProductionConfigurationError):
        TTSProductionConnection(
            registry, request.capability, policies.mapping, policies.operational, policies.retry,
            (override, replace(override, override_id="other")), 3, 9
        )


@pytest.mark.asyncio
async def test_production_connection_uses_provider_lease_resources_and_closes_once() -> None:
    policies = _policy(max_attempts=1)
    request = _request(bundle=policies)
    client = FakeTTS([_response()])
    discarded: list[str] = []
    released: list[TTSProviderClient] = []
    voice = request.voice_binding
    item = TTSProviderRegistration(
        voice.binding_id, voice.binding_revision, voice.provider_id,
        request.capability.provider_revision, lambda: client,
        lambda raw: _discard(discarded, raw), lambda value: _release(released, value),
    )
    connection = TTSProductionConnection(
        TTSProviderRegistry((item,)), request.capability, policies.mapping, policies.operational,
        policies.retry, request.pronunciation_overrides, 3, 9,
    )
    lease = await connection.acquire(voice)
    result = await lease.adapter.synthesize(request)
    assert result.artifact is not None
    await lease.resources.discard(PreparedAudioDiscardRequest(
        request.candidate_id, request.utterance.utterance_id,
        request.performance_plan.performance_plan_id, result.artifact.audio_ref,
        PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
    ))
    await lease.close()
    await lease.close()
    assert discarded == [_response().raw_audio_ref]
    assert released == [client]


@pytest.mark.asyncio
async def test_production_lease_closes_adapter_before_provider_lease() -> None:
    order: list[str] = []
    lease = _production_lease(
        _RecordingProductionAdapter(order), _RecordingProviderLease(order)
    )

    await lease.close()

    assert order == ["adapter.shutdown", "provider_lease.close"]


@pytest.mark.asyncio
async def test_production_lease_closes_provider_after_adapter_failure_once() -> None:
    order: list[str] = []
    raw_failure = RuntimeError("adapter-cleanup-sentinel")
    lease = _production_lease(
        _RecordingProductionAdapter(order, failure=raw_failure),
        _RecordingProviderLease(order),
    )

    with pytest.raises(TTSProductionCleanupError) as caught:
        await lease.close()
    with pytest.raises(TTSProductionCleanupError):
        await lease.close()

    assert order == ["adapter.shutdown", "provider_lease.close"]
    assert "adapter-cleanup-sentinel" not in str(caught.value)
    assert "adapter-cleanup-sentinel" not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
async def test_cancelled_production_lease_close_settles_provider_cleanup_once() -> None:
    order: list[str] = []
    entered = asyncio.Event()
    finish = asyncio.Event()
    lease = _production_lease(
        _RecordingProductionAdapter(order, entered=entered, finish=finish),
        _RecordingProviderLease(order),
    )

    closing = asyncio.create_task(lease.close())
    await entered.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await lease.close()

    assert order == ["adapter.shutdown", "provider_lease.close"]


async def _discard(values: list[str], raw: str) -> None:
    values.append(raw)


async def _release(values: list[TTSProviderClient], client: TTSProviderClient) -> None:
    values.append(client)
