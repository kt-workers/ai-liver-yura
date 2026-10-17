"""既存Ownerの本番構成を明示core起動へ結合する。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.bootstrap.core_components import compose_core_components
from app.usecases.cognition_delivery_configuration import CoreCognitionConfiguration
from app.usecases.speech_pipeline_production_configuration import (
    SpeechComponentProvenance,
    SpeechProductionInputs,
    create_production_speech_configuration,
)
from app.config.appraisal import load_appraisal_config
from app.config.appraisal_assembly import (
    AppraisalInitializationProvenance,
    AppraisalProductionBinding,
    build_appraisal_configuration,
)
from app.config.core import ConfigurationReference, CoreConfig, load_core_config
from app.config.core_contracts import (
    CoreConfigurationError,
    CoreFailureCode,
    identity,
    resource,
)
from app.config.executive import load_executive_config
from app.config.executive_assembly import (
    ExecutiveConfigurationProvenance,
    ExecutiveProductionBinding,
    create_executive_configuration,
)
from app.config.llm_connections import load_llm_connections
from app.domain.activity_binding import ActivityBindingAuthority
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.appraisal import DeterministicAppraisalRule
from app.domain.appraisal import descriptor as appraisal_descriptor
from app.domain.attention import AttentionSchedulingPolicy, AttentionTurnStore
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.common import require_aware
from app.domain.contracts.preconditions import PreconditionSourceBinding, PreconditionSourceRouter
from app.domain.executive.deliberator import descriptor as executive_descriptor
from app.domain.goals import GoalCommitmentStore
from app.domain.input_meaning.interpreter import descriptor as input_descriptor
from app.domain.plugin_registry import PluginRegistryAuthority
from app.infrastructure.llm.connection_registry_factory import (
    LLMConnectionAdapter,
    create_llm_connection_registry,
)
from app.infrastructure.llm.connections import route_llm_connections
from app.infrastructure.scheduling import RuntimeClock
from app.usecases.core_lifecycle import CoreActivationError, CoreApplicationLifecycle, stop_core
from app.usecases.input_reference_context import CoreInputReferenceContextBinding
from app.usecases.lifecycle import ApplicationLifecycle
from app.usecases.resource_cleanup import OwnedResourceLedger
from app.usecases.task_cleanup import reap_owned_task

if TYPE_CHECKING:
    from app.bootstrap.core_components import CoreComponents

ROOT = Path(__file__).resolve().parents[2]
CORE_RESOURCE = "config/core.yaml"
_OwnedResources = OwnedResourceLedger


@dataclass(frozen=True, slots=True)
class CoreRunIdentity:
    runtime_epoch: str
    system_run_id: str

    def __post_init__(self) -> None:
        identity(self.runtime_epoch)
        identity(self.system_run_id)


@dataclass(frozen=True, slots=True)
class ComponentBindings:
    core_config_id: str
    core_config_revision: int
    appraisal: AppraisalInitializationProvenance
    executive: ExecutiveConfigurationProvenance
    attention_policy_id: str
    attention_policy_revision: int
    speech: SpeechComponentProvenance | None = None


@dataclass(frozen=True, slots=True)
class SubsystemBinding:
    subsystem_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class LLMConnectionBinding:
    """本体が採用した接続IDだけを、Roleの実行内容なしに記録する。"""

    role_id: str
    connection_id: str


@dataclass(frozen=True, slots=True)
class SystemCompositionSnapshot:
    composition_id: str
    composition_revision: int
    config_id: str
    config_revision: int
    activation_id: str
    runtime_epoch: str
    system_run_id: str
    created_at: datetime
    character_id: str
    character_definition_revision: int
    component_bindings: tuple[ComponentBindings, ...]
    llm_connection_bindings: tuple[LLMConnectionBinding, ...]
    subsystem_bindings: tuple[SubsystemBinding, ...]
    requirements_generation: tuple[tuple[str, str | int], ...]


class CoreApplication:
    """構成情報を公開し、開始・終了を本体の実行所有者へ委譲する。"""

    __slots__ = (
        "core", "composition_snapshot", "cognition", "appraisal", "executive",
        "_owned", "_runtime",
    )

    def __init__(
        self,
        core: CoreComponents,
        composition_snapshot: SystemCompositionSnapshot,
        cognition: CoreCognitionConfiguration,
        appraisal: AppraisalProductionBinding,
        executive: ExecutiveProductionBinding,
        owned: _OwnedResources,
    ) -> None:
        self.core = core
        self.composition_snapshot = composition_snapshot
        self.cognition = cognition
        self.appraisal = appraisal
        self.executive = executive
        self._owned = owned
        self._runtime = CoreApplicationLifecycle(core, owned)

    async def start(self) -> None:
        try:
            await self._runtime.start()
        except CoreActivationError:
            raise CoreConfigurationError(CoreFailureCode.ACTIVATION_FAILED) from None

    async def stop(self) -> None:
        try:
            await self._runtime.stop()
        except asyncio.CancelledError:
            raise
        except CoreConfigurationError:
            raise
        except Exception:
            # 内部の回収例外を公開契約へ正規化し、詳細例外を外へ漏らさない。
            raise CoreConfigurationError(CoreFailureCode.INITIALIZATION_FAILED) from None


def _read(root: Path, ref: str) -> bytes:
    resource(ref)
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
    try:
        return path.read_bytes()
    except OSError:
        raise CoreConfigurationError(CoreFailureCode.MISSING_SYSTEM_CONFIG) from None


def _match(ref: ConfigurationReference, config_id: str, config_revision: int) -> None:
    if (ref.config_id, ref.config_revision) != (config_id, config_revision):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)


async def compose_core(
    *,
    run_identity: CoreRunIdentity,
    activation_id: str,
    fresh_start: bool,
    clock: RuntimeClock,
    registry: PluginRegistryAuthority,
    precondition_router: PreconditionSourceRouter,
    precondition_bindings: tuple[PreconditionSourceBinding, ...],
    activity_bindings: Mapping[str, ActivityBindingAuthority],
    fast_rules: tuple[DeterministicAppraisalRule, ...],
    llm_adapters: tuple[LLMConnectionAdapter, ...],
    speech: SpeechProductionInputs | None = None,
    config_ref: str = CORE_RESOURCE,
    resource_root: Path = ROOT,
) -> CoreApplication:
    from app.domain.activity_execution.speech_observation import SPEECH_OBSERVATION_POLICY

    owned = _OwnedResources()
    stage = CoreFailureCode.INVALID_SYSTEM_CONFIG
    try:
        if not isinstance(run_identity, CoreRunIdentity):
            raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
        config = load_core_config(_read(resource_root, config_ref))
        if activation_id != config.activation_id or fresh_start is not True:
            raise CoreConfigurationError(CoreFailureCode.ACTIVATION_FAILED)
        runtime = config
        character_ref = config.character_definition
        character = load_character_definition_yaml(_read(resource_root, character_ref.resource_ref))
        if (character.character_id, character.definition_revision) != (
            character_ref.character_id,
            character_ref.definition_revision,
        ):
            raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
        connections = load_llm_connections(
            _read(resource_root, config.llm_connections.resource_ref)
        )
        if (connections.config_id, connections.config_revision) != (
            config.llm_connections.config_id,
            config.llm_connections.config_revision,
        ):
            raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
        stage = CoreFailureCode.INITIALIZATION_FAILED
        goals = GoalCommitmentStore(bounds=BOUNDS)
        owned.add_sync(goals.finalization_participant.retire)
        activities = (
            ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
            if speech is not None else ActivityExecutionAuthority()
        )
        owned.add_sync(activities.finalization_participant.retire)
        reference = CoreInputReferenceContextBinding(
            goals, activities, runtime.input_meaning_policy, BOUNDS
        )
        source_revision = reference.snapshot().context.source_context_revision
        lifecycle = ApplicationLifecycle(clock, runtime.shutdown_policy)
        owned.actions.append(lifecycle.close)
        stage = CoreFailureCode.APPRAISAL_CONFIGURATION_FAILED
        appraisal_config = load_appraisal_config(
            _read(resource_root, config.appraisal_config.resource_ref)
        )
        _match(
            config.appraisal_config, appraisal_config.config_id, appraisal_config.config_revision
        )
        initialized_at = clock.now()
        require_aware(initialized_at, "initialized_at")
        appraisal = build_appraisal_configuration(
            appraisal_config,
            fresh_start=fresh_start,
            source_context_revision=source_revision,
            initialized_at=initialized_at.astimezone(timezone.utc),
            runtime_epoch=run_identity.runtime_epoch,
        )
        stage = CoreFailureCode.EXECUTIVE_CONFIGURATION_FAILED
        executive_config = load_executive_config(
            _read(resource_root, config.executive_config.resource_ref)
        )
        _match(
            config.executive_config, executive_config.config_id, executive_config.config_revision
        )
        executive = create_executive_configuration(
            executive_config, bounds=BOUNDS, activity_bindings=activity_bindings
        )
        owned.add_sync(executive.close)
        stage = CoreFailureCode.INITIALIZATION_FAILED
        attention_policy = AttentionSchedulingPolicy.production()
        if (attention_policy.policy_id, attention_policy.policy_revision) != (
            config.attention_policy.policy_id,
            config.attention_policy.policy_revision,
        ):
            raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
        attention = AttentionTurnStore(attention_policy)
        owned.add_sync(attention.finalization_participant.retire)
        stage = CoreFailureCode.PROVIDER_MAPPING_FAILED
        roles = (
            input_descriptor(runtime.input_meaning_policy),
            appraisal_descriptor(appraisal.appraisal_policy),
            executive_descriptor(executive.executive_policy),
        )
        connections_registry = await create_llm_connection_registry(
            connections, roles, llm_adapters
        )
        owned.actions.append(connections_registry.close)
        llm = route_llm_connections(
            connections_registry,
            (
                (roles[0], runtime.input_meaning_llm_connection_id),
                (roles[1], appraisal_config.llm_connection_id),
                (roles[2], executive_config.llm_connection_id),
            ),
        )
        stage = CoreFailureCode.COGNITION_COMPOSITION_FAILED
        speech_binding = None
        if speech is not None:
            speech_binding = await create_production_speech_configuration(
                speech, goals=goals, reference=reference, clock=clock,
                character_id=character.character_id,
                character_revision=character.definition_revision,
                runtime_epoch=run_identity.runtime_epoch, system_run_id=run_identity.system_run_id,
            )
            owned.actions.append(speech_binding.close)
        cognition = CoreCognitionConfiguration(
            appraisal.appraisal_policy,
            executive.executive_policy,
            appraisal.reducer,
            attention,
            executive.requirements_owner,
            registry,
            precondition_router,
            precondition_bindings,
            fast_rules,
            speech=None if speech_binding is None else speech_binding.configuration,
            decay_policy=appraisal.decay_policy,
        )
        core = compose_core_components(
            runtime,
            character,
            llm,
            goals,
            lifecycle=lifecycle,
            cognition=cognition,
            prepared_activities=activities,
            prepared_context=reference,
            prepared_clock=clock,
        )
        # 構築中の失敗にはCore全体の回収を登録し、正常返却時はアプリへ所有権を渡す。
        owned.actions.remove(lifecycle.close)

        async def close_untransferred_core() -> None:
            await stop_core(core)

        owned.actions.append(close_untransferred_core)
        stage = CoreFailureCode.INITIALIZATION_FAILED
        if speech_binding is not None:
            speech_binding.transfer_to_core(core)
            speech_binding.validate_current()
        if (
            reference.snapshot().context.source_context_revision != source_revision
            or executive.requirements_owner.current_generation() != executive.initial_generation
        ):
            raise CoreConfigurationError(stage)
        now = clock.now()
        require_aware(now, "created_at")
        snapshot = _snapshot(
            config,
            run_identity,
            now,
            character.character_id,
            character.definition_revision,
            runtime.config_id,
            runtime.config_revision,
            appraisal.provenance,
            executive.provenance,
            attention_policy,
            tuple(
                LLMConnectionBinding(role.role_id, connection_id)
                for role, connection_id in (
                    (roles[0], runtime.input_meaning_llm_connection_id),
                    (roles[1], appraisal_config.llm_connection_id),
                    (roles[2], executive_config.llm_connection_id),
                )
            ),
            None if speech_binding is None else speech_binding.provenance,
        )
        application = CoreApplication(core, snapshot, cognition, appraisal, executive, owned)
        owned.actions.remove(close_untransferred_core)
        return application
    except BaseException as error:
        try:
            await reap_owned_task(asyncio.create_task(owned.close()))
        except asyncio.CancelledError:
            raise
        except Exception:
            if not isinstance(error, asyncio.CancelledError):
                raise CoreConfigurationError(CoreFailureCode.INITIALIZATION_FAILED) from None
        if isinstance(error, asyncio.CancelledError):
            raise asyncio.CancelledError from None
        if isinstance(error, CoreConfigurationError):
            raise
        raise CoreConfigurationError(stage) from None


def _snapshot(
    config: CoreConfig,
    run: CoreRunIdentity,
    created_at: datetime,
    character_id: str,
    character_revision: int,
    core_config_id: str,
    core_config_revision: int,
    appraisal: AppraisalInitializationProvenance,
    executive: ExecutiveConfigurationProvenance,
    attention: AttentionSchedulingPolicy,
    llm_connections: tuple[LLMConnectionBinding, ...],
    speech: SpeechComponentProvenance | None = None,
) -> SystemCompositionSnapshot:
    return SystemCompositionSnapshot(
        config.composition_id,
        config.composition_revision,
        config.config_id,
        config.config_revision,
        config.activation_id,
        run.runtime_epoch,
        run.system_run_id,
        created_at.astimezone(timezone.utc),
        character_id,
        character_revision,
        (
            ComponentBindings(
                core_config_id,
                core_config_revision,
                appraisal,
                executive,
                attention.policy_id,
                attention.policy_revision,
                speech,
            ),
        ),
        llm_connections,
        (),
        executive.initial_generation_identity,
    )
