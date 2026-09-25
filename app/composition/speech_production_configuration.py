"""既存Speech Ownerの明示構成をS2へ渡し、構築途中の資源も回収する。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.composition.cognition import CoreCognitionDelivery
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.composition.presentation_notification import CorePresentationNotification
from app.composition.speech import CoreSpeechContextReaders, CoreSpeechPipeline
from app.composition.speech_configuration import CoreSpeechConfiguration
from app.composition.speech_preparation import finish_cleanup
from app.composition.speech_semantics_policy import bind_speech_semantics_policy_v1
from app.composition.speech_semantics_sources import ProductionSpeechSources
from app.config.s2_contracts import S2ConfigurationError, S2FailureCode, identity, revision
from app.domain.brain_integration import BrainIntegrationWork
from app.domain.character_language import CharacterLanguageAuthority, CharacterLanguageRealizer
from app.domain.character_language.realizer import (
    CharacterLanguageLiveStatePort,
    CharacterLanguagePolicy,
)
from app.domain.character_language.realizer import (
    descriptor as character_descriptor,
)
from app.domain.executive import CommittedExecutiveDecision
from app.domain.goals import GoalCommitmentStore
from app.domain.llm import LLMRoleDescriptor
from app.domain.semantic_verification import SemanticVerificationAuthority, SemanticVerifier
from app.domain.semantic_verification.verifier import (
    SemanticVerificationLiveStatePort,
    SemanticVerificationPolicy,
    blind_descriptor,
    relation_descriptor,
)
from app.domain.speech_performance import SpeechPerformancePlanner
from app.domain.speech_performance.contracts import SpeechPerformanceProjectionPolicy
from app.domain.speech_runtime.admission import SpeechPreparationAdmission
from app.domain.speech_runtime.contracts import SpeechPresentationMode, TTSPreparationMode
from app.domain.speech_runtime.discard import PreparedAudioDiscarder, PreparedAudioDiscardPort
from app.domain.speech_runtime.policy import SpeechCandidatePriority, SpeechRuntimeOperationalPolicy
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueCoordinator
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.shutdown import SpeechRuntimeShutdown
from app.domain.speech_runtime.tasks import CandidateTaskRegistry
from app.domain.speech_semantics import SpeechSemanticAuthority, SpeechSemanticsPlanner
from app.domain.speech_semantics.planner import (
    SpeechSemanticsLiveStatePort,
    SpeechSemanticsPolicy,
)
from app.domain.speech_semantics.planner import (
    descriptor as semantics_descriptor,
)
from app.domain.speech_semantics.production import SpeechSemanticPolicyOwner
from app.infrastructure.speech_presentation.supervisor import SpeechPresentationWorkerSupervisor
from app.runtime.kernel import RuntimeClock
from app.usecases.ports.llm import LLMRolePort

if TYPE_CHECKING:
    from app.bootstrap import MinimumCoreApplication


@dataclass(frozen=True, slots=True)
class SpeechBindingReference:
    """秘密や具体提供先設定を含まないdeploymentの公開参照。"""

    identity: str
    revision: int
    availability: str

    def __post_init__(self) -> None:
        identity(self.identity)
        revision(self.revision)
        if self.availability not in ("available", "unavailable"):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)


@dataclass(frozen=True, slots=True)
class SpeechProductionPublication:
    """供給元が同一世代で変更しない本番policyと構成参照。"""

    source_id: str
    config_id: str
    config_revision: int
    binding_id: str
    binding_revision: int
    binding_generation: int
    character_id: str
    character_revision: int
    semantics: SpeechSemanticsPolicy
    character: CharacterLanguagePolicy
    verifier: SemanticVerificationPolicy
    performance: SpeechPerformanceProjectionPolicy
    runtime: SpeechRuntimeOperationalPolicy
    provider: SpeechBindingReference
    tts: SpeechBindingReference
    presentation: SpeechBindingReference
    output_modes: tuple[SpeechPresentationMode, ...]
    tts_mode: TTSPreparationMode
    priority: SpeechCandidatePriority
    expiry_policy_ref: str

    def __post_init__(self) -> None:
        for value in (
            self.source_id,
            self.config_id,
            self.binding_id,
            self.character_id,
            self.expiry_policy_ref,
        ):
            identity(value)
        for number in (
            self.config_revision,
            self.binding_revision,
            self.binding_generation,
            self.character_revision,
        ):
            revision(number)
        for instance, expected in (
            (self.semantics, SpeechSemanticsPolicy),
            (self.character, CharacterLanguagePolicy),
            (self.verifier, SemanticVerificationPolicy),
            (self.performance, SpeechPerformanceProjectionPolicy),
            (self.runtime, SpeechRuntimeOperationalPolicy),
            (self.provider, SpeechBindingReference),
            (self.tts, SpeechBindingReference),
            (self.presentation, SpeechBindingReference),
        ):
            if not isinstance(instance, expected):
                raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        if (
            type(self.output_modes) is not tuple
            or not self.output_modes
            or len(set(self.output_modes)) != len(self.output_modes)
            or any(
                not isinstance(mode, SpeechPresentationMode)
                or mode
                not in (SpeechPresentationMode.TEXT_ONLY, SpeechPresentationMode.AUDIO_WITH_TEXT)
                for mode in self.output_modes
            )
            or not isinstance(self.priority, SpeechCandidatePriority)
            or self.tts_mode
            not in (
                TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
                TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE,
            )
        ):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)

        for policy in (
            self.semantics.execution,
            self.character.execution,
            self.verifier.blind_execution,
            self.verifier.relation_execution,
        ):
            identity(policy.policy_id)
            revision(policy.policy_revision, minimum=0)
        for policy_id in (self.performance.policy_id, self.runtime.policy_id):
            identity(policy_id)

    def roles(self) -> tuple[LLMRoleDescriptor, ...]:
        return (
            semantics_descriptor(self.semantics),
            character_descriptor(self.character),
            blind_descriptor(self.verifier),
            relation_descriptor(self.verifier),
        )


@dataclass(frozen=True, slots=True)
class SpeechProductionPorts:
    """外部資源Ownerが同じbindingに束ねた公開port。共有clientは借用する。"""

    publication: SpeechProductionPublication
    roles: tuple[LLMRoleDescriptor, ...]
    llm: LLMRolePort
    semantic_live: SpeechSemanticsLiveStatePort
    character_live: CharacterLanguageLiveStatePort
    verifier_live: SemanticVerificationLiveStatePort
    discard: PreparedAudioDiscardPort
    presentation: SpeechPresentationWorkerSupervisor
    readers: Callable[
        [CoreCognitionDelivery, CoreInputReferenceContextBinding], CoreSpeechContextReaders
    ]
    notification: Callable[
        [
            CoreCognitionDelivery,
            CoreInputReferenceContextBinding,
            BrainIntegrationWork,
            CommittedExecutiveDecision,
            str,
        ],
        CorePresentationNotification,
    ]
    release: Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SpeechProductionInputs:
    """deploymentと既存Ownerの明示入力。既定値や試験fallbackを持たない。"""

    publication: SpeechProductionPublication
    current_publication: Callable[[], SpeechProductionPublication]
    semantic_owner: SpeechSemanticPolicyOwner
    memory: CoreMemoryPersistenceBinding
    acquire: Callable[
        [SpeechProductionPublication, tuple[LLMRoleDescriptor, ...]],
        Awaitable[SpeechProductionPorts],
    ]


@dataclass(frozen=True, slots=True)
class SpeechComponentProvenance:
    source_id: str
    config_id: str
    config_revision: int
    binding_id: str
    binding_revision: int
    binding_generation: int
    character_id: str
    character_revision: int
    runtime_epoch: str
    system_run_id: str
    semantic_policy_id: str
    semantic_policy_revision: int
    execution_policies: tuple[tuple[str, str, int], ...]
    performance_policy_id: str
    performance_policy_revision: int
    runtime_policy_id: str
    runtime_policy_revision: int
    provider: SpeechBindingReference
    tts: SpeechBindingReference
    presentation: SpeechBindingReference
    output_modes: tuple[str, ...]
    tts_mode: str


class SpeechProductionBinding:
    """Coreへ移管する資源と、Systemが保持するleaseの回収を分ける。"""

    def __init__(
        self,
        inputs: SpeechProductionInputs,
        ports: SpeechProductionPorts,
        goals: GoalCommitmentStore,
        reference: CoreInputReferenceContextBinding,
        clock: RuntimeClock,
        runtime_epoch: str,
        system_run_id: str,
    ) -> None:
        self._inputs, self._ports, self._reference = inputs, ports, reference
        self._clock = clock
        self._publication = inputs.publication
        self._semantic_publication = inputs.semantic_owner.publication()
        self._semantic = bind_speech_semantics_policy_v1(
            inputs.semantic_owner,
            sources=ProductionSpeechSources(
                goals=goals, memory=inputs.memory, execution=reference.activities
            ),
        )
        p = self._publication
        if p.semantics.meaning_policy != self._semantic_publication.value.meaning:
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        self.runtime = SpeechRuntime(p.runtime, clock.now)
        self._tasks = CandidateTaskRegistry()
        self._discarder = PreparedAudioDiscarder(self.runtime, ports.discard)
        self._shutdown = SpeechRuntimeShutdown(
            self.runtime,
            self._tasks,
            PreparedSpeechQueueCoordinator(
                self.runtime, PreparedSpeechQueue(p.runtime), self._discarder
            ),
            self._discarder,
        )
        self.pipeline: CoreSpeechPipeline | None = None
        self._built = False
        self._transferred = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self.configuration = CoreSpeechConfiguration(self._semantic.executive_evidence, self._build)
        meaning = self._semantic_publication.value.meaning
        assert meaning is not None
        subject = self._semantic_publication.value.projection.runtime_subject_identity
        if subject is None or (subject.character_id, subject.character_definition_revision) != (
            p.character_id,
            p.character_revision,
        ):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        identity(meaning.policy_id)
        self.provenance = SpeechComponentProvenance(
            p.source_id,
            p.config_id,
            p.config_revision,
            p.binding_id,
            p.binding_revision,
            p.binding_generation,
            p.character_id,
            p.character_revision,
            runtime_epoch,
            system_run_id,
            meaning.policy_id,
            meaning.revision,
            tuple(
                (
                    r.role_id,
                    r.default_execution_policy.policy_id,
                    r.default_execution_policy.policy_revision,
                )
                for r in p.roles()
            ),
            p.performance.policy_id,
            p.performance.policy_revision,
            p.runtime.policy_id,
            p.runtime.policy_revision,
            p.provider,
            p.tts,
            p.presentation,
            tuple(m.value for m in p.output_modes),
            p.tts_mode.value,
        )

    def validate_current(self) -> None:
        if (
            self._closed
            or self._inputs.current_publication() != self._publication
            or self._inputs.semantic_owner.publication() != self._semantic_publication
            or self.runtime.operational_policy != self._publication.runtime
        ):
            raise S2ConfigurationError(S2FailureCode.INITIALIZATION_FAILED)

    def _build(
        self,
        cognition: CoreCognitionDelivery,
        reference: CoreInputReferenceContextBinding,
    ) -> tuple[CoreSpeechPipeline, SpeechRuntimeShutdown]:
        self.validate_current()
        if self._built or reference is not self._reference:
            raise S2ConfigurationError(S2FailureCode.COGNITION_COMPOSITION_FAILED)
        self._built = True
        p, ports = self._publication, self._ports
        readers = ports.readers(cognition, reference)
        if not isinstance(readers, CoreSpeechContextReaders):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        self.pipeline = CoreSpeechPipeline(
            self._semantic.context_builder,
            SpeechSemanticsPlanner(
                ports.llm, ports.semantic_live, SpeechSemanticAuthority(), p.semantics
            ),
            CharacterLanguageRealizer(
                ports.llm, ports.character_live, CharacterLanguageAuthority(), p.character
            ),
            SemanticVerifier(
                ports.llm, ports.verifier_live, SemanticVerificationAuthority(), p.verifier
            ),
            SpeechPerformancePlanner(p.performance),
            self.runtime,
            SpeechPresentationExecutor(self.runtime, self._tasks),
            ports.presentation,
            readers,
            self._clock.now,
            lambda work, decision, pid: ports.notification(
                cognition, reference, work, decision, pid
            ),
            p.priority,
            p.expiry_policy_ref,
            SpeechPreparationAdmission(p.runtime),
            self._discarder,
            ports.discard,
            p.output_modes,
            p.tts_mode,
        )
        self.validate_current()
        return self.pipeline, self._shutdown

    def transfer_to_core(self, core: MinimumCoreApplication) -> None:
        if (
            self._closed
            or self._transferred
            or self.pipeline is None
            or core.cognition is None
            or core.cognition.speech is None
            or core.cognition.speech.pipeline is not self.pipeline
            or core.cognition.speech.shutdown is not self._shutdown
            or core.input_context is not self._reference
        ):
            raise S2ConfigurationError(S2FailureCode.INITIALIZATION_FAILED)
        self._transferred = True

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close())
        await finish_cleanup(self._close_task)

    async def _close(self) -> None:
        failed = False
        cancelled = False
        actions: list[Callable[[], Awaitable[object]]] = []
        if not self._transferred:
            if self.pipeline is not None:
                actions.append(self.pipeline.close)
            actions.append(self._shutdown.close)
        actions.append(self._ports.release)
        for action in actions:
            try:
                await action()
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failed = True
        if cancelled:
            raise asyncio.CancelledError
        if failed:
            raise S2ConfigurationError(S2FailureCode.INITIALIZATION_FAILED)


async def create_production_speech_configuration(
    inputs: SpeechProductionInputs,
    *,
    goals: GoalCommitmentStore,
    reference: CoreInputReferenceContextBinding,
    clock: RuntimeClock,
    character_id: str,
    character_revision: int,
    runtime_epoch: str,
    system_run_id: str,
) -> SpeechProductionBinding:
    """返却済みleaseを直ちに所有し、未構築・不一致を成功にしない。"""
    if not isinstance(inputs, SpeechProductionInputs):
        raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
    p = inputs.publication
    if (
        not isinstance(p, SpeechProductionPublication)
        or not isinstance(inputs.semantic_owner, SpeechSemanticPolicyOwner)
        or not isinstance(inputs.memory, CoreMemoryPersistenceBinding)
        or (p.character_id, p.character_revision) != (character_id, character_revision)
    ):
        raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
    identity(runtime_epoch)
    identity(system_run_id)
    if inputs.current_publication() != p:
        raise S2ConfigurationError(S2FailureCode.INITIALIZATION_FAILED)
    ports = await inputs.acquire(p, p.roles())
    if not isinstance(ports, SpeechProductionPorts):
        raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
    binding: SpeechProductionBinding | None = None
    try:
        if (
            ports.publication != p
            or ports.roles != p.roles()
            or not isinstance(ports.presentation, SpeechPresentationWorkerSupervisor)
            or not callable(ports.discard.discard)
        ):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        binding = SpeechProductionBinding(
            inputs, ports, goals, reference, clock, runtime_epoch, system_run_id
        )
        binding.validate_current()
        return binding
    except BaseException as error:
        try:

            async def cleanup() -> None:
                if binding is None:
                    await ports.release()
                else:
                    await binding.close()

            await finish_cleanup(asyncio.create_task(cleanup()))
        except BaseException:
            if isinstance(error, asyncio.CancelledError):
                raise asyncio.CancelledError from None
            raise S2ConfigurationError(S2FailureCode.INITIALIZATION_FAILED) from None
        if isinstance(error, (asyncio.CancelledError, S2ConfigurationError)):
            raise
        raise S2ConfigurationError(S2FailureCode.COGNITION_COMPOSITION_FAILED) from None
