"""既存の本番Ownerを束ね、Speech deploymentの外部portを供給する。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from app.adapters.tts.contracts import TTSSynthesisPriority, TTSSynthesisRequest, TTSSynthesisStatus
from app.adapters.tts.production import TTSProductionConnection, TTSProductionLease
from app.composition.cognition import CoreCognitionDelivery
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.presentation_notification import (
    CorePresentationNotification,
    CoreSpeechProductionOwnerConnection,
)
from app.composition.s2_provider import S2ProviderLease, S2ProviderLeaseFactory
from app.composition.speech import CoreSpeechContextReaders, SpeechOutputPreparationRequest
from app.composition.speech_deployment import SpeechDeploymentRequest
from app.composition.speech_preparation import finish_cleanup
from app.composition.speech_production_configuration import SpeechProductionPorts
from app.config.layered import ConfigurationError, ConfigurationFailureCode
from app.domain.brain_integration import BrainIntegrationWork
from app.domain.executive import CommittedExecutiveDecision
from app.domain.speech_runtime.contracts import SpeechPresentationMode, TTSPreparationMode
from app.domain.speech_runtime.discard import PreparedAudioDiscardPort, PreparedAudioDiscardRequest
from app.infrastructure.speech_presentation.production import (
    PresentationWorkerBinding,
    PresentationWorkerLease,
    PresentationWorkerRegistry,
)

if TYPE_CHECKING:
    from app.domain.character_language.realizer import CharacterLanguageLiveStatePort
    from app.domain.semantic_verification.verifier import SemanticVerificationLiveStatePort
    from app.domain.speech_semantics.planner import SpeechSemanticsLiveStatePort


class SpeechDeploymentFactoryError(RuntimeError):
    """公開済み設定から本番Speech portを安全に構成できない。"""


class _TextOnlyDiscardPort(PreparedAudioDiscardPort):
    """音声を生成しない明示modeで、架空のaudio回収を受理しない。"""

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        raise SpeechDeploymentFactoryError("TEXT_ONLY構成に音声回収要求は使用できません")


OwnerConnectionResolver = Callable[
    [CoreCognitionDelivery, CoreInputReferenceContextBinding], CoreSpeechProductionOwnerConnection
]
ReaderFactory = Callable[
    [CoreCognitionDelivery, CoreInputReferenceContextBinding], CoreSpeechContextReaders
]


class _ClosableLease(Protocol):
    async def close(self) -> None: ...


class _ReleasableLease(Protocol):
    async def release(self) -> None: ...


class _TTSRequestIdentity(Protocol):
    @property
    def candidate_id(self) -> str: ...

    @property
    def candidate_generation(self) -> int: ...

    @property
    def performance_generation(self) -> int: ...


class _TTSMappingIdentity(Protocol):
    @property
    def mapping_id(self) -> str: ...

    @property
    def mapping_revision(self) -> int: ...


class _TTSConnectionIdentity(Protocol):
    @property
    def mapping(self) -> _TTSMappingIdentity: ...


class _BoundOwnerConnection:
    """一つの#702構成ハンドルに同期結合した#721 Ownerを固定する。"""

    def __init__(
        self,
        resolver: OwnerConnectionResolver,
        reader_factory: ReaderFactory,
        output: Callable[
            [SpeechOutputPreparationRequest],
            Awaitable[tuple[SpeechPresentationMode, str | None]],
        ],
    ) -> None:
        self._resolver = resolver
        self._reader_factory = reader_factory
        self._output = output
        self._connection: CoreSpeechProductionOwnerConnection | None = None
        self._cognition: CoreCognitionDelivery | None = None
        self._reference: CoreInputReferenceContextBinding | None = None

    def readers(
        self,
        cognition: CoreCognitionDelivery,
        reference: CoreInputReferenceContextBinding,
    ) -> CoreSpeechContextReaders:
        if self._connection is not None:
            raise SpeechDeploymentFactoryError("Speech Owner接続は一度だけ構成できます")
        connection = self._resolver(cognition, reference)
        if (
            not isinstance(connection, CoreSpeechProductionOwnerConnection)
            or connection.cognition is not cognition
            or connection.reference is not reference
        ):
            raise SpeechDeploymentFactoryError("Speech Owner graphが一致しません")
        try:
            readers = connection.readers(self._reader_factory)
        except (TypeError, ValueError) as error:
            raise SpeechDeploymentFactoryError("Speech本番reader接続が不正です") from error
        self._connection = connection
        self._cognition = cognition
        self._reference = reference
        return replace(readers, output=self._output)

    def notification(
        self,
        cognition: CoreCognitionDelivery,
        reference: CoreInputReferenceContextBinding,
        work: BrainIntegrationWork,
        decision: CommittedExecutiveDecision,
        presentation_id: str,
    ) -> CorePresentationNotification:
        if (
            self._connection is None
            or cognition is not self._cognition
            or reference is not self._reference
        ):
            raise SpeechDeploymentFactoryError("Speech Owner接続が未結合又は不一致です")
        try:
            return self._connection.notification(work, decision, presentation_id)
        except (TypeError, ValueError) as error:
            raise SpeechDeploymentFactoryError("Speech本番通知接続が不正です") from error


def speech_tts_request_id(
    request: _TTSRequestIdentity,
    connection: _TTSConnectionIdentity,
    voice_binding_id: str,
    voice_binding_revision: int,
) -> str:
    """公開由来だけを固定JSONへ正規化したTTS request identityを返す。"""
    material = {
        "candidate_generation": request.candidate_generation,
        "candidate_id": request.candidate_id,
        "mapping_id": connection.mapping.mapping_id,
        "mapping_revision": connection.mapping.mapping_revision,
        "performance_generation": request.performance_generation,
        "voice_binding_id": voice_binding_id,
        "voice_binding_revision": voice_binding_revision,
    }
    encoded = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return "tts-" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SpeechDeploymentOwnerConnections:
    """設定値ではなく起動rootだけが注入する既存Owner接続。"""

    provider_factory: S2ProviderLeaseFactory
    tts: TTSProductionConnection
    presentation: PresentationWorkerRegistry
    owner_connection: OwnerConnectionResolver
    reader_factory: ReaderFactory
    semantic_live: SpeechSemanticsLiveStatePort
    character_live: CharacterLanguageLiveStatePort
    verifier_live: SemanticVerificationLiveStatePort

    def __post_init__(self) -> None:
        if not all(
            callable(value)
            for value in (self.provider_factory, self.reader_factory, self.owner_connection)
        ) or not isinstance(self.tts, TTSProductionConnection) or not isinstance(
            self.presentation, PresentationWorkerRegistry
        ):
            raise SpeechDeploymentFactoryError("Speech本番Owner接続が不正です")


class ProductionSpeechDeploymentPortFactory:
    """返却前の全leaseを回収し、返却後のreleaseを一つに束ねる。"""

    def __init__(self, connections: SpeechDeploymentOwnerConnections) -> None:
        if not isinstance(connections, SpeechDeploymentOwnerConnections):
            raise SpeechDeploymentFactoryError("Speech本番factory入力が不正です")
        self._connections = connections

    async def __call__(self, request: SpeechDeploymentRequest) -> SpeechProductionPorts:
        if not isinstance(request, SpeechDeploymentRequest):
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
        provider: S2ProviderLease | None = None
        tts: TTSProductionLease | None = None
        presentation: PresentationWorkerLease | None = None
        try:
            provider_roles, configs, bindings, mode = request.provider_bindings.factory_inputs()
            if provider_roles != request.provider_roles or tuple(
                role.role_id for role in provider_roles
            ) != tuple(
                role.role_id for role in request.publication.roles()
            ):
                raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
            provider = await self._connections.provider_factory(
                provider_roles, configs, bindings, mode
            )
            if not isinstance(provider, S2ProviderLease) or provider.bindings != bindings:
                raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
            audio_enabled = (
                SpeechPresentationMode.AUDIO_WITH_TEXT in request.publication.output_modes
            )
            if audio_enabled and request.voice is None:
                raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
            if audio_enabled:
                assert request.voice is not None
                tts = await self._connections.tts.acquire(request.voice)
            presentation = await self._connections.presentation.acquire(
                PresentationWorkerBinding(
                    request.publication.presentation.identity,
                    request.publication.presentation.revision,
                    request.publication.presentation.availability,
                )
            )
            output = self._output(request, tts)
            owner_binding = _BoundOwnerConnection(
                self._connections.owner_connection,
                self._connections.reader_factory,
                output,
            )
            return SpeechProductionPorts(
                request.publication,
                request.publication.roles(),
                provider.port,
                self._connections.semantic_live,
                self._connections.character_live,
                self._connections.verifier_live,
                tts.resources if tts is not None else _TextOnlyDiscardPort(),
                presentation.supervisor,
                owner_binding.readers,
                owner_binding.notification,
                self._release(provider, tts, presentation),
            )
        except BaseException:
            await self._cleanup(provider, tts, presentation)
            raise

    def _output(
        self, deployment: SpeechDeploymentRequest, lease: TTSProductionLease | None
    ) -> Callable[
        [SpeechOutputPreparationRequest],
        Awaitable[tuple[SpeechPresentationMode, str | None]],
    ]:

        async def output(
            request: SpeechOutputPreparationRequest,
        ) -> tuple[SpeechPresentationMode, str | None]:
            if lease is None:
                if deployment.publication.output_modes != (SpeechPresentationMode.TEXT_ONLY,):
                    raise SpeechDeploymentFactoryError("Speech TTS bindingがありません")
                return SpeechPresentationMode.TEXT_ONLY, None
            if request.preparation_disposition is TTSPreparationMode.DISABLED:
                raise SpeechDeploymentFactoryError("Speech TTS準備modeが不正です")
            priority = (
                TTSSynthesisPriority.SPECULATIVE
                if request.preparation_disposition
                is TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE
                else TTSSynthesisPriority.FOREGROUND
            )
            voice = deployment.voice
            if voice is None:
                raise SpeechDeploymentFactoryError("Speech TTS bindingがありません")
            synthesis = TTSSynthesisRequest(
                speech_tts_request_id(
                    request,
                    self._connections.tts,
                    voice.binding_id,
                    voice.binding_revision,
                ),
                request.candidate_id,
                request.utterance,
                request.performance_plan,
                voice,
                self._connections.tts.capability,
                self._connections.tts.pronunciation_overrides,
                self._connections.tts.provider_config_revision,
                self._connections.tts.pronunciation_config_revision,
                self._connections.tts.mapping.mapping_id,
                self._connections.tts.mapping.mapping_revision,
                self._connections.tts.retry.policy_id,
                self._connections.tts.retry.policy_revision,
                priority,
                request.created_at,
                request.trace_id,
                request.deadline_at,
            )
            result = await lease.adapter.synthesize(synthesis)
            if result.status is not TTSSynthesisStatus.SUCCEEDED or result.artifact is None:
                raise SpeechDeploymentFactoryError("Speech音声準備に失敗しました")
            return SpeechPresentationMode.AUDIO_WITH_TEXT, result.artifact.audio_ref

        return output

    @staticmethod
    async def _cleanup(
        provider: _ReleasableLease | None,
        tts: _ClosableLease | None,
        presentation: _ClosableLease | None,
    ) -> None:
        async def cleanup() -> None:
            failure: BaseException | None = None
            for lease in (presentation, tts):
                if lease is None:
                    continue
                try:
                    await lease.close()
                except asyncio.CancelledError as error:
                    if failure is None:
                        failure = error
                except Exception:
                    if failure is None:
                        failure = SpeechDeploymentFactoryError("Speech本番leaseを回収できません")
            if provider is not None:
                try:
                    await provider.release()
                except asyncio.CancelledError as error:
                    if failure is None:
                        failure = error
                except Exception:
                    if failure is None:
                        failure = SpeechDeploymentFactoryError("Speech本番leaseを回収できません")
            if failure is not None:
                if isinstance(failure, asyncio.CancelledError):
                    raise asyncio.CancelledError
                raise failure

        await finish_cleanup(asyncio.create_task(cleanup()))

    @staticmethod
    def _release(
        provider: _ReleasableLease,
        tts: _ClosableLease | None,
        presentation: _ClosableLease,
    ) -> Callable[[], Awaitable[None]]:
        released: asyncio.Task[None] | None = None

        async def release() -> None:
            nonlocal released
            if released is None:
                released = asyncio.create_task(
                    ProductionSpeechDeploymentPortFactory._cleanup(provider, tts, presentation)
                )
            await finish_cleanup(released)

        return release
