"""リビジョン付き設定と既存所有者を結合し、ゆら本体を起動・停止する。"""

from __future__ import annotations

import asyncio
import signal
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm.connections import production_llm_connection_adapters
from app.adapters.llm.production import create_openai_port_from_environment
from app.bootstrap.core_components import CoreComponents as CoreComponents
from app.bootstrap.core_components import compose_core_components
from app.composition.cognition_configuration import CoreCognitionConfiguration
from app.composition.speech_production_configuration import SpeechProductionInputs
from app.composition.system_cognition_configuration import (
    CORE_RESOURCE,
    ROOT,
    CoreApplication,
    CoreRunIdentity,
    compose_core,
)
from app.config.core import CoreConfig, load_core_config
from app.config.core_contracts import CoreConfigurationError
from app.config.layered import ConfigurationError, load_user_configuration
from app.domain.activity_binding import ActivityBindingAuthority
from app.domain.appraisal import DeterministicAppraisalRule
from app.domain.appraisal import descriptor as appraisal_descriptor
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.character.contracts import CharacterDefinitionDocument
from app.domain.contracts.common import require_identifier
from app.domain.contracts.preconditions import PreconditionSourceBinding, PreconditionSourceRouter
from app.domain.executive.deliberator import descriptor as executive_descriptor
from app.domain.goals import GoalCommitmentStore
from app.domain.input_meaning.interpreter import descriptor
from app.domain.llm import LLMRoleDescriptor
from app.domain.memory_reflection.llm_roles import proposal_descriptor, support_descriptor
from app.domain.plugin_registry import PluginRegistryAuthority
from app.domain.speech_semantics.production import SpeechSemanticPolicyOwner
from app.infrastructure.llm.connection_registry_factory import LLMConnectionAdapter
from app.infrastructure.persistence import PostgresPersistenceRuntime
from app.infrastructure.scheduling import RuntimeClock, SystemRuntimeClock
from app.usecases.brain_input_meaning import (
    InputMeaningBrainModulePort as InputMeaningBrainModulePort,
)
from app.usecases.brain_input_meaning import (
    InputMeaningBrainWorkPayload as InputMeaningBrainWorkPayload,
)
from app.usecases.brain_input_meaning import (
    UnavailableInputMeaningLiveContextPort as UnavailableInputMeaningLiveContextPort,
)
from app.usecases.core_lifecycle import start_core as start_core
from app.usecases.core_lifecycle import stop_core as stop_core
from app.usecases.goal_persistence import CoreGoalPersistenceBinding
from app.usecases.lifecycle import ApplicationLifecycle, DependencyRetryPolicy
from app.usecases.memory_persistence import CoreMemoryPersistenceBinding
from app.usecases.ports.llm import LLMRolePort
from app.usecases.task_cleanup import reap_owned_task as _reap_cleanup

_compose_core = compose_core_components

if TYPE_CHECKING:
    from app.composition.speech_deployment import SpeechDeploymentRegistry


@dataclass(frozen=True, slots=True)
class CoreSpeechOwners:
    """Speech有効時だけ起動rootへ明示注入する既存の本番Owner集合。"""

    semantic_owner: SpeechSemanticPolicyOwner
    memory: CoreMemoryPersistenceBinding
    registry: SpeechDeploymentRegistry


@dataclass(frozen=True, slots=True)
class CoreRuntimeOwners:
    """本体起動rootが生成又は借用する既存Runtime Ownerの入力。"""

    registry: PluginRegistryAuthority
    precondition_router: PreconditionSourceRouter
    precondition_bindings: tuple[PreconditionSourceBinding, ...]
    activity_bindings: Mapping[str, ActivityBindingAuthority]
    fast_rules: tuple[DeterministicAppraisalRule, ...]
    speech: CoreSpeechOwners | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.registry, PluginRegistryAuthority) or not isinstance(
            self.precondition_router, PreconditionSourceRouter
        ):
            raise ValueError("本体起動には既存Runtime Ownerの明示入力が必要です")
        object.__setattr__(self, "precondition_bindings", tuple(self.precondition_bindings))
        object.__setattr__(self, "fast_rules", tuple(self.fast_rules))
        object.__setattr__(
            self,
            "activity_bindings",
            MappingProxyType(dict(self.activity_bindings)),
        )
        if self.speech is not None and not isinstance(self.speech, CoreSpeechOwners):
            raise ValueError("Speech起動には既存Speech Ownerの明示入力が必要です")


def default_core_runtime_owners() -> CoreRuntimeOwners:
    """外部能力を補作せず、空の既存Owner集合を新runへ供給する。"""
    return CoreRuntimeOwners(
        registry=PluginRegistryAuthority(),
        precondition_router=PreconditionSourceRouter(()),
        precondition_bindings=(),
        activity_bindings={},
        fast_rules=(),
    )


def build_core_runtime(
    config_path: Path | None = None, *, cognition: CoreCognitionConfiguration | None = None
) -> CoreComponents:
    """本番設定を読み、提供サービスの構成不備は既存契約のまま伝える。"""
    config, character, llm = _load_core(config_path, cognition)
    return _compose_core(
        config,
        character,
        llm,
        GoalCommitmentStore(bounds=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY),
        cognition=cognition,
    )


def _load_core(
    config_path: Path | None,
    cognition: CoreCognitionConfiguration | None = None,
) -> tuple[CoreConfig, CharacterDefinitionDocument, LLMRolePort]:
    root = Path(__file__).resolve().parent.parent
    path = (
        config_path if config_path is not None else root / "config/core.yaml"
    )
    config = load_core_config(path.read_bytes())
    character = load_character_definition_yaml(
        (root / config.character_definition.resource_ref).read_bytes()
    )
    roles: tuple[LLMRoleDescriptor, ...] = (descriptor(config.input_meaning_policy),)
    if cognition is not None:
        roles += (
            appraisal_descriptor(cognition.appraisal_policy),
            executive_descriptor(cognition.executive_policy),
        )
        if cognition.reflection is not None:
            roles += (
                proposal_descriptor(cognition.reflection.roles),
                support_descriptor(cognition.reflection.roles),
            )
    llm = create_openai_port_from_environment(roles)
    return config, character, llm


async def build_persistent_core(
    config_path: Path,
    *,
    persistence: PostgresPersistenceRuntime,
    retry_policy: DependencyRetryPolicy,
    runtime_epoch: str,
    max_pending_memory: int,
    cognition: CoreCognitionConfiguration | None = None,
) -> CoreComponents:
    """明示された保存実行基盤を所有し、復元した目標を本体へ接続する。"""
    if not isinstance(persistence, PostgresPersistenceRuntime):
        raise ValueError("本体の保存構成にはPostgresPersistenceRuntimeが必要です")
    app: CoreComponents | None = None
    memory: CoreMemoryPersistenceBinding | None = None
    lifecycle: ApplicationLifecycle | None = None
    try:
        require_identifier(runtime_epoch, "runtime_epoch")
        if not isinstance(retry_policy, DependencyRetryPolicy):
            raise ValueError("保存接続には型付きの再接続方針が必要です")
        config, character, llm = _load_core(config_path, cognition)
        shutdown = config.shutdown_policy
        if (
            shutdown.final_persistence_grace_seconds <= 0
            or shutdown.resource_close_grace_seconds <= 0
        ):
            raise ValueError("保存を使う起動には正の最終保存・資源終了猶予が必要です")
        memory = CoreMemoryPersistenceBinding(persistence, max_pending=max_pending_memory)
        lifecycle = ApplicationLifecycle(SystemRuntimeClock(), config.shutdown_policy)
        persistence.attach(lifecycle, retry_policy)
        await persistence.start()
        goals = await CoreGoalPersistenceBinding.restore(persistence, runtime_epoch=runtime_epoch)
        app = _compose_core(config, character, llm, goals, memory, lifecycle, cognition)
        return app
    except BaseException:

        async def cleanup() -> None:
            try:
                if app is not None:
                    await stop_core(app)
                else:
                    try:
                        if memory is not None:
                            await memory.close()
                    finally:
                        if lifecycle is not None:
                            await lifecycle.close()
            finally:
                # 登録前の失敗でも引き受けた実行群・DB資源を回収する。
                await persistence.close()

        await _reap_cleanup(asyncio.create_task(cleanup()))
        raise


async def run_core_runtime() -> None:
    """停止通知まで待機し、シグナル登録と所有タスクを確実に片付ける。"""
    app = build_core_runtime()
    loop = asyncio.get_running_loop()
    stop_requested = asyncio.Event()
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    registered: list[signal.Signals] = []
    try:
        for signum in previous:
            loop.add_signal_handler(signum, stop_requested.set)
            registered.append(signum)
        await app.start()
        print("本体の実行構成が起動しました。", flush=True)
        await stop_requested.wait()
    finally:
        try:
            await app.stop()
        finally:
            for signum in registered:
                loop.remove_signal_handler(signum)
                signal.signal(signum, previous[signum])


def _new_core_run_identity() -> CoreRunIdentity:
    """本体の一回の起動へ、新しい実行識別子を与える。"""
    return CoreRunIdentity(
        f"core-epoch-{uuid.uuid4().hex}",
        f"core-run-{uuid.uuid4().hex}",
    )


def _load_core_speech(
    run: CoreRunIdentity,
    owners: CoreRuntimeOwners,
) -> SpeechProductionInputs | None:
    """三層設定のSpeech有効化だけを既存登録済みOwnerへ接続する。"""
    root = ROOT / "config"
    try:
        configuration = load_user_configuration(root)
        if configuration.speech is None:
            return None
        if owners.speech is None:
            raise ValueError("Speech本番接続が登録されていません")
        from app.composition.speech_deployment import create_speech_deployment

        source = create_speech_deployment(
            root,
            run=run,
            semantic_owner=owners.speech.semantic_owner,
            memory=owners.speech.memory,
            registry=owners.speech.registry,
        )
        if source is None:
            raise ValueError("Speech設定の状態が一致しません")
        return source.inputs
    except ConfigurationError:
        raise ValueError("Speech本番設定または登録を使用できません") from None


async def build_core_application(
    owners: CoreRuntimeOwners | None = None,
) -> CoreApplication:
    """通常CLIが使用する本体構成を、既存公開factoryだけで組み立てる。"""
    runtime_owners = owners or default_core_runtime_owners()
    run = _new_core_run_identity()
    speech = _load_core_speech(run, runtime_owners)
    return await build_core(
        run_identity=run,
        activation_id="yura.core.explicit",
        fresh_start=True,
        clock=SystemRuntimeClock(),
        registry=runtime_owners.registry,
        precondition_router=runtime_owners.precondition_router,
        precondition_bindings=runtime_owners.precondition_bindings,
        activity_bindings=runtime_owners.activity_bindings,
        fast_rules=runtime_owners.fast_rules,
        llm_adapters=production_llm_connection_adapters(),
        speech=speech,
    )


async def run_core() -> None:
    """本体を開始し、停止通知まで所有資源を保持する。"""
    app = await build_core_application()
    loop = asyncio.get_running_loop()
    stop_requested = asyncio.Event()
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    registered: list[signal.Signals] = []
    try:
        for signum in previous:
            loop.add_signal_handler(signum, stop_requested.set)
            registered.append(signum)
        await app.start()
        print("ゆら本体の起動が完了しました。", flush=True)
        await stop_requested.wait()
    finally:
        try:
            await app.stop()
        finally:
            for signum in registered:
                loop.remove_signal_handler(signum)
                signal.signal(signum, previous[signum])


def main() -> None:
    arguments = tuple(sys.argv[1:])
    if arguments:
        print("使用方法: python -m app", file=sys.stderr)
        raise SystemExit(2)
    try:
        asyncio.run(run_core())
    except CoreConfigurationError as error:
        print(
            f"ゆら本体の構成、起動または停止に失敗しました: {error.code.value}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (OSError, ValueError, RuntimeError):
        print("ゆら本体の構成、起動または停止に失敗しました。", file=sys.stderr)
        raise SystemExit(1) from None


async def build_core(
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
    llm_adapters: tuple[LLMConnectionAdapter, ...] = (),
    speech: SpeechProductionInputs | None = None,
    config_ref: str = CORE_RESOURCE,
    resource_root: Path = ROOT,
) -> CoreApplication:
    """本体要求だけを構築し、別構成へfallbackしない。"""
    return await compose_core(
        run_identity=run_identity,
        activation_id=activation_id,
        fresh_start=fresh_start,
        clock=clock,
        registry=registry,
        precondition_router=precondition_router,
        precondition_bindings=precondition_bindings,
        activity_bindings=activity_bindings,
        fast_rules=fast_rules,
        llm_adapters=llm_adapters,
        speech=speech,
        config_ref=config_ref,
        resource_root=resource_root,
    )
