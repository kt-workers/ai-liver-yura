"""既存Ownerの本番構成を明示S2起動へ結合する。"""

from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.composition.appraisal_configuration import (
    AppraisalInitializationProvenance,
    build_appraisal_configuration,
)
from app.composition.cognition_configuration import CoreCognitionConfiguration
from app.composition.executive_configuration import (
    ExecutiveConfigurationProvenance,
    create_executive_configuration,
)
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.s2_provider import (
    ProviderBindingSnapshot,
    S2ProviderConfigurationSource,
    S2ProviderLease,
    S2ProviderLeaseFactory,
    resolve_provider_configuration,
)
from app.config.appraisal import load_appraisal_config
from app.config.cognition_s2 import ConfigurationReference, S2ProductionConfig, load_s2_config
from app.config.executive import load_executive_config
from app.config.minimum_brain import load_minimum_brain_config
from app.config.provider_deployment import load_provider_deployment
from app.config.s2_contracts import (
    S2ConfigurationError,
    S2FailureCode,
    identity,
    resource,
)
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
from app.runtime.kernel import RuntimeClock
from app.runtime.lifecycle import RuntimeLifecycle

if TYPE_CHECKING:
    from app.bootstrap import MinimumCoreApplication

ROOT = Path(__file__).resolve().parents[2]
S2_RESOURCE = "resources/config/v2/cognition_s2.yaml"


@dataclass(frozen=True, slots=True)
class S2RunIdentity:
    git_head: str
    runtime_epoch: str
    system_run_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.git_head, str)
            or re.fullmatch(r"[0-9a-f]{40}", self.git_head) is None
        ):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        identity(self.runtime_epoch)
        identity(self.system_run_id)


@dataclass(frozen=True, slots=True)
class ComponentBindings:
    minimum_config_id: str
    minimum_config_revision: int
    appraisal: AppraisalInitializationProvenance
    executive: ExecutiveConfigurationProvenance
    attention_policy_id: str
    attention_policy_revision: int


@dataclass(frozen=True, slots=True)
class SubsystemBinding:
    subsystem_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class SystemCompositionSnapshot:
    composition_id: str
    composition_revision: int
    config_id: str
    config_revision: int
    activation_id: str
    git_head: str
    runtime_epoch: str
    system_run_id: str
    created_at: datetime
    character_id: str
    character_definition_revision: int
    component_bindings: tuple[ComponentBindings, ...]
    provider_bindings: tuple[ProviderBindingSnapshot, ...]
    subsystem_bindings: tuple[SubsystemBinding, ...]
    requirements_generation: tuple[tuple[str, str | int], ...]


class _OwnedResources:
    """生成済み資源だけを逆順に、一度だけ回収する台帳。"""

    def __init__(self) -> None:
        self.actions: list[Callable[[], Awaitable[None]]] = []

    def add_sync(self, operation: Callable[[], None]) -> None:
        async def close() -> None:
            operation()

        self.actions.append(close)

    async def close(self) -> None:
        failed = False
        cancelled = False
        while self.actions:
            try:
                await self.actions.pop()()
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failed = True
        if cancelled:
            raise asyncio.CancelledError
        if failed:
            raise S2ConfigurationError(S2FailureCode.INITIALIZATION_FAILED)


@dataclass(frozen=True, slots=True)
class S2ProductionApplication:
    core: MinimumCoreApplication
    composition_snapshot: SystemCompositionSnapshot
    cognition: CoreCognitionConfiguration
    _owned: _OwnedResources = field(repr=False)
    _stop_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _start_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    async def start(self) -> None:
        if self._stop_task is not None:
            raise S2ConfigurationError(S2FailureCode.ACTIVATION_FAILED)
        if self._start_task is None:
            object.__setattr__(self, "_start_task", asyncio.create_task(self.core.start()))
        assert self._start_task is not None
        try:
            await asyncio.shield(self._start_task)
        except BaseException as error:
            self._start_task.cancel()
            from app.bootstrap import _reap_cleanup

            try:
                await _reap_cleanup(self._start_task)
            except (Exception, asyncio.CancelledError):
                pass
            try:
                await self.stop()
            finally:
                if isinstance(error, asyncio.CancelledError):
                    raise asyncio.CancelledError from None
                raise S2ConfigurationError(S2FailureCode.ACTIVATION_FAILED) from None

    async def stop(self) -> None:
        from app.bootstrap import _reap_cleanup

        if self._stop_task is None:
            object.__setattr__(self, "_stop_task", asyncio.create_task(self._close()))
        assert self._stop_task is not None
        await _reap_cleanup(self._stop_task)

    async def _close(self) -> None:
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await self._start_task
            except (Exception, asyncio.CancelledError):
                pass
        await self._owned.close()


def current_artifact_head() -> str:
    """System起動側でcheckoutを照合し、dirty treeをexact HEAD証拠にしない。"""
    try:
        state = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        )
        if state.stdout:
            raise ValueError
        return head.stdout.strip()
    except Exception:
        raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG) from None


def _read(root: Path, ref: str) -> bytes:
    resource(ref)
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()):
        raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
    try:
        return path.read_bytes()
    except OSError:
        raise S2ConfigurationError(S2FailureCode.MISSING_SYSTEM_CONFIG) from None


def _match(ref: ConfigurationReference, config_id: str, config_revision: int) -> None:
    if (ref.config_id, ref.config_revision) != (config_id, config_revision):
        raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)


async def compose_s2_production_core(
    *,
    run_identity: S2RunIdentity,
    activation_id: str,
    fresh_start: bool,
    clock: RuntimeClock,
    registry: PluginRegistryAuthority,
    precondition_router: PreconditionSourceRouter,
    precondition_bindings: tuple[PreconditionSourceBinding, ...],
    activity_bindings: Mapping[str, ActivityBindingAuthority],
    fast_rules: tuple[DeterministicAppraisalRule, ...],
    provider_source: S2ProviderConfigurationSource | None,
    provider_factory: S2ProviderLeaseFactory,
    config_ref: str = S2_RESOURCE,
    resource_root: Path = ROOT,
    artifact_head: Callable[[], str] = current_artifact_head,
) -> S2ProductionApplication:
    from app.bootstrap import _compose_core, _reap_cleanup

    owned = _OwnedResources()
    stage = S2FailureCode.INVALID_SYSTEM_CONFIG
    try:
        if not isinstance(run_identity, S2RunIdentity) or artifact_head() != run_identity.git_head:
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        config = load_s2_config(_read(resource_root, config_ref))
        if activation_id != config.activation_id or fresh_start is not True:
            raise S2ConfigurationError(S2FailureCode.ACTIVATION_FAILED)
        minimum = load_minimum_brain_config(
            _read(resource_root, config.minimum_config.resource_ref)
        )
        _match(config.minimum_config, minimum.config_id, minimum.config_revision)
        character_ref = config.character_definition
        if minimum.character_definition_path != character_ref.resource_ref:
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        character = load_character_definition_yaml(_read(resource_root, character_ref.resource_ref))
        if (character.character_id, character.definition_revision) != (
            character_ref.character_id,
            character_ref.definition_revision,
        ):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        deployment = load_provider_deployment(
            _read(resource_root, config.provider_deployment.resource_ref)
        )
        if (deployment.deployment_id, deployment.deployment_revision) != (
            config.provider_deployment.deployment_id,
            config.provider_deployment.deployment_revision,
        ):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        stage = S2FailureCode.INITIALIZATION_FAILED
        goals = GoalCommitmentStore(bounds=BOUNDS)
        owned.add_sync(goals.finalization_participant.retire)
        activities = ActivityExecutionAuthority()
        owned.add_sync(activities.finalization_participant.retire)
        reference = CoreInputReferenceContextBinding(
            goals, activities, minimum.input_meaning_policy, BOUNDS
        )
        source_revision = reference.snapshot().context.source_context_revision
        lifecycle = RuntimeLifecycle(clock, minimum.shutdown_policy)
        owned.actions.append(lifecycle.close)
        stage = S2FailureCode.APPRAISAL_CONFIGURATION_FAILED
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
        stage = S2FailureCode.EXECUTIVE_CONFIGURATION_FAILED
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
        stage = S2FailureCode.INITIALIZATION_FAILED
        attention_policy = AttentionSchedulingPolicy.production()
        if (attention_policy.policy_id, attention_policy.policy_revision) != (
            config.attention_policy.policy_id,
            config.attention_policy.policy_revision,
        ):
            raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)
        attention = AttentionTurnStore(attention_policy)
        owned.add_sync(attention.finalization_participant.retire)
        stage = S2FailureCode.PROVIDER_MAPPING_FAILED
        roles = (
            input_descriptor(minimum.input_meaning_policy),
            appraisal_descriptor(appraisal.appraisal_policy),
            executive_descriptor(executive.executive_policy),
        )
        provider_configs, bindings = resolve_provider_configuration(
            deployment, roles, provider_source
        )
        mode = deployment.role_bindings[0].availability_mode
        lease = await provider_factory(roles, provider_configs, bindings, mode)
        if not isinstance(lease, S2ProviderLease):
            raise S2ConfigurationError(stage)
        owned.actions.append(lease.release)
        if lease.bindings != bindings or lease.availability_mode != mode:
            raise S2ConfigurationError(stage)
        if resolve_provider_configuration(deployment, roles, provider_source) != (
            provider_configs,
            bindings,
        ):
            raise S2ConfigurationError(S2FailureCode.PROVIDER_MAPPING_FAILED)
        stage = S2FailureCode.COGNITION_COMPOSITION_FAILED
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
        )
        core = _compose_core(
            minimum,
            character,
            lease.port,
            goals,
            lifecycle=lifecycle,
            cognition=cognition,
            prepared_activities=activities,
            prepared_context=reference,
            prepared_clock=clock,
        )
        # Foundationの終了をCoreへ移管して二重回収を防ぐ。
        owned.actions.remove(lifecycle.close)
        owned.actions.append(core.stop)
        stage = S2FailureCode.INITIALIZATION_FAILED
        if (
            reference.snapshot().context.source_context_revision != source_revision
            or executive.requirements_owner.current_generation() != executive.initial_generation
            or artifact_head() != run_identity.git_head
        ):
            raise S2ConfigurationError(stage)
        now = clock.now()
        require_aware(now, "created_at")
        snapshot = _snapshot(
            config,
            run_identity,
            now,
            character.character_id,
            character.definition_revision,
            minimum.config_id,
            minimum.config_revision,
            appraisal.provenance,
            executive.provenance,
            attention_policy,
            lease.bindings,
        )
        return S2ProductionApplication(core, snapshot, cognition, owned)
    except BaseException as error:
        try:
            await _reap_cleanup(asyncio.create_task(owned.close()))
        except asyncio.CancelledError:
            raise
        except Exception:
            if not isinstance(error, asyncio.CancelledError):
                raise S2ConfigurationError(S2FailureCode.INITIALIZATION_FAILED) from None
        if isinstance(error, asyncio.CancelledError):
            raise asyncio.CancelledError from None
        if isinstance(error, S2ConfigurationError):
            raise
        raise S2ConfigurationError(stage) from None


def _snapshot(
    config: S2ProductionConfig,
    run: S2RunIdentity,
    created_at: datetime,
    character_id: str,
    character_revision: int,
    minimum_id: str,
    minimum_revision: int,
    appraisal: AppraisalInitializationProvenance,
    executive: ExecutiveConfigurationProvenance,
    attention: AttentionSchedulingPolicy,
    providers: tuple[ProviderBindingSnapshot, ...],
) -> SystemCompositionSnapshot:
    return SystemCompositionSnapshot(
        config.composition_id,
        config.composition_revision,
        config.config_id,
        config.config_revision,
        config.activation_id,
        run.git_head,
        run.runtime_epoch,
        run.system_run_id,
        created_at.astimezone(timezone.utc),
        character_id,
        character_revision,
        (
            ComponentBindings(
                minimum_id,
                minimum_revision,
                appraisal,
                executive,
                attention.policy_id,
                attention.policy_revision,
            ),
        ),
        providers,
        (),
        executive.initial_generation_identity,
    )
