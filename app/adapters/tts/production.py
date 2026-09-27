"""信頼済みTTS提供元を明示登録し、音声資源の回収を同じOwnerへ閉じ込める。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.domain.contracts.common import require_identifier, require_revision
from app.domain.speech_runtime.discard import PreparedAudioDiscardPort, PreparedAudioDiscardRequest

from .contracts import TTSCapabilityView, TTSVoiceBinding
from .provider import PreparedAudioResourceStore, TTSProviderClient


class TTSProductionConfigurationError(ValueError):
    """信頼済み登録と要求されたbindingが一致しない。"""


class TTSProductionCleanupError(RuntimeError):
    """非公開のprovider資源を回収できなかった。"""


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

    def acquire(self, binding: TTSVoiceBinding, capability: TTSCapabilityView) -> TTSProviderLease:
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
        if not callable(getattr(client, "synthesize", None)):
            raise TTSProductionConfigurationError("TTS clientが不正です")
        return TTSProviderLease(
            client,
            ProductionPreparedAudioResources(registration.discard_raw_resource),
            registration.release_client,
        )
