"""信頼済みTTS提供元を明示登録し、音声資源の回収を同じOwnerへ閉じ込める。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.domain.contracts.common import require_identifier, require_revision
from app.domain.speech_runtime.discard import PreparedAudioDiscardPort, PreparedAudioDiscardRequest
from app.runtime.lifecycle import DependencyRetryPolicy

from .contracts import PronunciationOverrideView, TTSCapabilityView, TTSVoiceBinding
from .d10_provider import TTSProviderAdapter
from .policy import (
    TTSPerformanceMappingPolicy,
    TTSProviderOperationalPolicy,
    validate_tts_policy_bundle,
)
from .provider import PreparedAudioResourceStore, TTSProviderClient


class TTSProductionConfigurationError(ValueError):
    """信頼済み登録と要求されたbindingが一致しない。"""


class TTSProductionCleanupError(RuntimeError):
    """非公開のprovider資源を回収できなかった。"""


@dataclass(frozen=True, slots=True)
class TTSProductionConnection:
    """構成rootが同一provider世代として注入する本番TTS接続。"""

    registry: TTSProviderRegistry
    capability: TTSCapabilityView
    mapping: TTSPerformanceMappingPolicy
    operational: TTSProviderOperationalPolicy
    retry: DependencyRetryPolicy
    pronunciation_overrides: tuple[PronunciationOverrideView, ...]
    pronunciation_config_revision: int
    provider_config_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.registry, TTSProviderRegistry):
            raise TTSProductionConfigurationError("TTS registryが不正です")
        try:
            validate_tts_policy_bundle(self.mapping, self.operational, self.retry)
            if not (
                self.capability.provider_id
                == self.mapping.provider_id
                == self.operational.provider_id
                == self.retry.dependency_id
                and self.capability.provider_revision
                == self.mapping.provider_revision
                == self.operational.provider_revision
            ):
                raise ValueError
            require_revision(self.pronunciation_config_revision, "pronunciation_config_revision")
            require_revision(self.provider_config_revision, "provider_config_revision")
        except (TypeError, ValueError):
            raise TTSProductionConfigurationError("TTS production世代が一致しません") from None
        overrides = tuple(self.pronunciation_overrides)
        if any(not isinstance(item, PronunciationOverrideView) for item in overrides) or len(
            {item.override_id for item in overrides}
        ) != len(overrides) or len({item.surface for item in overrides}) != len(overrides):
            raise TTSProductionConfigurationError("発音overrideが不正です")
        object.__setattr__(self, "pronunciation_overrides", overrides)

    async def acquire(self, voice: TTSVoiceBinding) -> TTSProductionLease:
        if not isinstance(voice, TTSVoiceBinding) or (
            voice.provider_id != self.capability.provider_id
            or voice.binding_revision != self.capability.voice_binding_revision
        ):
            raise TTSProductionConfigurationError("TTS voice bindingが一致しません")
        lease = await self.registry.acquire(voice, self.capability)
        try:
            adapter = TTSProviderAdapter(
                lease.client,
                self.mapping,
                self.operational,
                self.retry,
                resource_store=lease.resources,
            )
            return TTSProductionLease(adapter, lease)
        except BaseException:
            await lease.close()
            raise


class TTSProductionLease:
    """adapter停止後に#710 leaseを回収する本番所有handle。"""

    def __init__(self, adapter: TTSProviderAdapter, provider_lease: TTSProviderLease) -> None:
        self.adapter = adapter
        self.resources = provider_lease.resources
        self._provider_lease = provider_lease
        self._close_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await ProductionPreparedAudioResources._settle(self._close_task)

    async def _close(self) -> None:
        failed = False
        try:
            await self.adapter.shutdown()
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
        try:
            await self._provider_lease.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
        if failed:
            raise TTSProductionCleanupError("TTS本番leaseを回収できません")


@dataclass(frozen=True, slots=True)
class TTSProviderRegistration:
    """構成rootだけが作る、一つのprovider/binding世代の登録。"""

    binding_id: str
    binding_revision: int
    provider_id: str
    provider_revision: int
    create_client: Callable[[], TTSProviderClient]
    discard_raw_resource: Callable[[str], Awaitable[None]]
    release_client: Callable[[TTSProviderClient], Awaitable[None]]

    def __post_init__(self) -> None:
        for name in ("binding_id", "provider_id"):
            require_identifier(getattr(self, name), name)
        require_revision(self.binding_revision, "binding_revision")
        require_revision(self.provider_revision, "provider_revision")
        if not all(
            callable(value)
            for value in (self.create_client, self.discard_raw_resource, self.release_client)
        ):
            raise TTSProductionConfigurationError("TTS提供元登録が不正です")


class ProductionPreparedAudioResources(PreparedAudioResourceStore, PreparedAudioDiscardPort):
    """公開audio_refとproviderの生handleを分離し、回収を一度だけ実行する。"""

    def __init__(self, discard_raw_resource: Callable[[str], Awaitable[None]]) -> None:
        if not callable(discard_raw_resource):
            raise TTSProductionConfigurationError("音声資源の回収登録が不正です")
        self._discard_raw_resource = discard_raw_resource
        self._resources: dict[str, str] = {}
        self._discard_tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    def store(self, artifact_id: str, request_id: str, raw_resource_ref: str) -> str:
        if self._closed:
            raise TTSProductionCleanupError("終了済み音声資源へ保存できません")
        for name, value in (("artifact_id", artifact_id), ("request_id", request_id)):
            require_identifier(value, name)
        if not isinstance(raw_resource_ref, str) or not raw_resource_ref:
            raise TTSProductionConfigurationError("音声資源参照が不正です")
        material = f"{artifact_id}\x1f{request_id}\x1f{raw_resource_ref}"
        safe_ref = "artifact://prepared/" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        if safe_ref in self._discard_tasks:
            raise TTSProductionCleanupError("回収済み音声資源を再利用できません")
        prior = self._resources.get(safe_ref)
        if prior is not None and prior != raw_resource_ref:
            raise TTSProductionConfigurationError("音声資源参照が衝突しました")
        self._resources[safe_ref] = raw_resource_ref
        return safe_ref

    def resolve(self, artifact_ref: str) -> str | None:
        if not isinstance(artifact_ref, str):
            return None
        return self._resources.get(artifact_ref)

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        if not isinstance(request, PreparedAudioDiscardRequest):
            raise TTSProductionConfigurationError("音声破棄要求が不正です")
        task = self._discard_tasks.get(request.audio_ref)
        if task is None:
            raw_resource_ref = self._resources.pop(request.audio_ref, None)
            if raw_resource_ref is None:
                return
            task = asyncio.create_task(self._discard(raw_resource_ref))
            self._discard_tasks[request.audio_ref] = task
        await self._settle(task)

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await self._settle(self._close_task)

    async def _close(self) -> None:
        self._closed = True
        for audio_ref, raw_resource_ref in tuple(self._resources.items()):
            self._resources.pop(audio_ref, None)
            self._discard_tasks.setdefault(
                audio_ref, asyncio.create_task(self._discard(raw_resource_ref))
            )
        if self._discard_tasks:
            results = await asyncio.gather(*self._discard_tasks.values(), return_exceptions=True)
            if any(isinstance(result, BaseException) for result in results):
                raise TTSProductionCleanupError("音声資源を回収できません")

    async def _discard(self, raw_resource_ref: str) -> None:
        try:
            await self._discard_raw_resource(raw_resource_ref)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise TTSProductionCleanupError("音声資源を回収できません") from None

    @staticmethod
    async def _settle(task: asyncio.Task[None]) -> None:
        cancelled = False
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError


class TTSProviderLease:
    """clientとそのartifact Ownerを同じlifecycleで返す借用handle。"""

    def __init__(
        self,
        client: TTSProviderClient,
        resources: ProductionPreparedAudioResources,
        release_client: Callable[[TTSProviderClient], Awaitable[None]],
    ) -> None:
        self.client = client
        self.resources = resources
        self._release_client = release_client
        self._close_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await ProductionPreparedAudioResources._settle(self._close_task)

    async def _close(self) -> None:
        failed = False
        try:
            await self.resources.close()
        except Exception:
            failed = True
        try:
            await self._release_client(self.client)
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
        if failed:
            raise TTSProductionCleanupError("TTS提供元を回収できません")


class TTSProviderRegistry:
    """任意importを許さず、trusted codeの完全一致登録だけを解決する。"""

    def __init__(self, registrations: tuple[TTSProviderRegistration, ...]) -> None:
        if type(registrations) is not tuple or any(
            not isinstance(item, TTSProviderRegistration) for item in registrations
        ):
            raise TTSProductionConfigurationError("TTS提供元登録tupleが不正です")
        indexed = {(item.binding_id, item.binding_revision): item for item in registrations}
        if len(indexed) != len(registrations):
            raise TTSProductionConfigurationError("TTS binding登録が重複しています")
        self._registrations = indexed

    async def acquire(
        self, binding: TTSVoiceBinding, capability: TTSCapabilityView
    ) -> TTSProviderLease:
        if not isinstance(binding, TTSVoiceBinding) or not isinstance(
            capability, TTSCapabilityView
        ):
            raise TTSProductionConfigurationError("TTS binding要求が不正です")
        registration = self._registrations.get((binding.binding_id, binding.binding_revision))
        if (
            registration is None
            or not binding.enabled
            or capability.provider_id != binding.provider_id
            or capability.voice_binding_revision != binding.binding_revision
            or registration.provider_id != binding.provider_id
            or registration.provider_revision != capability.provider_revision
        ):
            raise TTSProductionConfigurationError("TTS提供元bindingが登録と一致しません")
        try:
            client = registration.create_client()
        except Exception:
            raise TTSProductionConfigurationError("TTS clientを取得できません") from None
        try:
            if not callable(getattr(client, "synthesize", None)):
                raise TTSProductionConfigurationError("TTS clientが不正です")
            return TTSProviderLease(
                client,
                ProductionPreparedAudioResources(registration.discard_raw_resource),
                registration.release_client,
            )
        except BaseException:
            await self._release_failed_acquisition(registration, client)
            raise

    @staticmethod
    async def _release_failed_acquisition(
        registration: TTSProviderRegistration, client: TTSProviderClient
    ) -> None:
        """lease返却前のclientを、呼出側の取消より先に必ず回収する。"""

        async def release() -> None:
            await registration.release_client(client)

        task = asyncio.create_task(release())
        try:
            await ProductionPreparedAudioResources._settle(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise TTSProductionCleanupError("取得中のTTS提供元を回収できません") from None
            raise
        except Exception:
            raise TTSProductionCleanupError("取得中のTTS提供元を回収できません") from None
