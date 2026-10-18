"""統合Coreの設定読込、非永続・永続構成と取得失敗時の資源回収。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm.production import create_openai_port_from_environment
from app.bootstrap.cognition_configuration import CoreCognitionConfiguration
from app.bootstrap.core_components import CoreComponents, compose_core_components
from app.bootstrap.runtime_application import CoreRuntimeApplication
from app.config.core import CoreConfig, load_core_config
from app.domain.appraisal import descriptor as appraisal_descriptor
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.character.contracts import CharacterDefinitionDocument
from app.domain.contracts.common import require_identifier
from app.domain.executive.deliberator import descriptor as executive_descriptor
from app.domain.goals import GoalCommitmentStore
from app.domain.input_meaning.interpreter import descriptor
from app.domain.llm import LLMRoleDescriptor
from app.domain.memory_reflection.llm_roles import proposal_descriptor, support_descriptor
from app.infrastructure.persistence import PostgresPersistenceRuntime
from app.infrastructure.scheduling import SystemRuntimeClock
from app.usecases.core_lifecycle import stop_core
from app.usecases.goal_persistence import CoreGoalPersistenceBinding
from app.usecases.lifecycle import ApplicationLifecycle, DependencyRetryPolicy
from app.usecases.memory_persistence import CoreMemoryPersistenceBinding
from app.usecases.ports.llm import LLMRolePort
from app.usecases.task_cleanup import reap_owned_task as _reap_cleanup

_compose_core = compose_core_components

def build_core_runtime(
    config_path: Path | None = None, *, cognition: CoreCognitionConfiguration | None = None
) -> CoreRuntimeApplication:
    """既存構成APIを維持しつつ、全Brainを必須とする。"""
    if cognition is None:
        raise ValueError("統合本体の認知構成は必須です")
    config, character, llm = _load_core(config_path, cognition)
    components = _compose_core(
        config,
        character,
        llm,
        GoalCommitmentStore(bounds=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY),
        cognition=cognition,
    )
    return CoreRuntimeApplication(components)


def _load_core(
    config_path: Path | None,
    cognition: CoreCognitionConfiguration | None = None,
) -> tuple[CoreConfig, CharacterDefinitionDocument, LLMRolePort]:
    root = Path(__file__).resolve().parents[2]
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
    cognition_factory: (
        Callable[[CoreConfig, CoreGoalPersistenceBinding, str], CoreCognitionConfiguration] | None
    ) = None,
) -> CoreRuntimeApplication:
    """保存基盤と復元済み目標を構成し、実行ライフサイクルを委譲する。"""
    if (cognition is None) == (cognition_factory is None):
        raise ValueError("認知構成か信頼済み認知生成元を一つだけ指定してください")
    if not isinstance(persistence, PostgresPersistenceRuntime):
        raise ValueError("本体の保存構成にはPostgresPersistenceRuntimeが必要です")
    app: CoreComponents | None = None
    memory: CoreMemoryPersistenceBinding | None = None
    lifecycle: ApplicationLifecycle | None = None
    try:
        require_identifier(runtime_epoch, "runtime_epoch")
        if not isinstance(retry_policy, DependencyRetryPolicy):
            raise ValueError("保存接続には型付きの再接続方針が必要です")
        if cognition_factory is None:
            config, character, llm = _load_core(config_path, cognition)
        else:
            # 復元Goalができる前に認知Ownerを代作しない。
            config = load_core_config(config_path.read_bytes())
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
        if cognition_factory is not None:
            cognition = cognition_factory(config, goals, runtime_epoch)
            if not isinstance(cognition, CoreCognitionConfiguration):
                raise ValueError("認知生成元が型付き本番構成を返していません")
            loaded_config, character, llm = _load_core(config_path, cognition)
            if loaded_config != config:
                raise ValueError("保存用の本体構成が起動中に変更されました")
        app = _compose_core(config, character, llm, goals, memory, lifecycle, cognition)
        return CoreRuntimeApplication(app)
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
