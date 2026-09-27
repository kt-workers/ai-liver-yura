from __future__ import annotations

import asyncio
from typing import cast

import pytest

from app.adapters.tts.contracts import TTSCapabilityView, TTSVoiceBinding
from app.adapters.tts.d10_provider import TTSProviderAdapter
from app.adapters.tts.production import (
    TTSProductionConfigurationError,
    TTSProviderRegistration,
    TTSProviderRegistry,
)
from app.adapters.tts.provider import ProviderSynthesisInput, TTSProviderClient, TTSProviderResponse
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
    lease = TTSProviderRegistry((registration(client, discarded, released),)).acquire(
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
    await lease.close()
    await lease.close()
    assert released == [client]


def test_missing_or_mismatched_binding_fails_without_provider_fallback() -> None:
    client = FakeTTSClient()
    registry = TTSProviderRegistry((registration(client, [], []),))

    with pytest.raises(TTSProductionConfigurationError, match="登録と一致"):
        registry.acquire(binding(provider_id="other"), capability(provider_id="other"))
    with pytest.raises(TTSProductionConfigurationError, match="登録と一致"):
        registry.acquire(binding(), capability(revision=2))


@pytest.mark.asyncio
async def test_close_recovers_undiscarded_artifacts_and_client() -> None:
    client = FakeTTSClient()
    discarded: list[str] = []
    released: list[TTSProviderClient] = []
    lease = TTSProviderRegistry((registration(client, discarded, released),)).acquire(
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
    lease = TTSProviderRegistry((item,)).acquire(binding(), capability())
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
    lease = TTSProviderRegistry((item,)).acquire(voice, request.capability)
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


def test_duplicate_registration_and_invalid_client_are_rejected() -> None:
    client = FakeTTSClient()
    item = registration(client, [], [])
    with pytest.raises(TTSProductionConfigurationError, match="重複"):
        TTSProviderRegistry((item, item))

    invalid = TTSProviderRegistration(
        "yura_tts",
        1,
        "provider",
        7,
        lambda: cast(TTSProviderClient, object()),
        item.discard_raw_resource,
        item.release_client,
    )
    with pytest.raises(TTSProductionConfigurationError, match="clientが不正"):
        TTSProviderRegistry((invalid,)).acquire(binding(), capability())
