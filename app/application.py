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
from typing import TYPE_CHECKING, TypeVar

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm.connections import production_llm_connection_adapters
from app.adapters.llm.production import create_openai_port_from_environment
from app.composition.cognition import CoreCognitionDelivery
from app.composition.cognition_configuration import CoreCognitionConfiguration
from app.composition.input_reference_context import CoreInputReferenceContextBinding
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
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.appraisal import DeterministicAppraisalRule
from app.domain.appraisal import descriptor as appraisal_descriptor
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.character.contracts import CharacterDefinitionDocument
from app.domain.contracts.common import require_identifier
from app.domain.contracts.lifecycle import (
    ApplicationShutdownError,
    ApplicationShutdownFailure,
    ApplicationShutdownStage,
)
from app.domain.contracts.preconditions import PreconditionSourceBinding, PreconditionSourceRouter
from app.domain.contracts.semantic_subject import RuntimeSubjectIdentity
from app.domain.executive.deliberator import descriptor as executive_descriptor
from app.domain.goals import GoalCommitmentStore
from app.domain.input_gateway import InputAdmission, NormalizedInputEvent
from app.domain.input_meaning import (
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    ReferenceContext,
)
from app.domain.input_meaning.interpreter import descriptor
from app.domain.llm import LLMRoleDescriptor
from app.domain.memory_reflection.llm_roles import proposal_descriptor, support_descriptor
from app.domain.plugin_registry import PluginRegistryAuthority
from app.domain.speech_semantics.production import SpeechSemanticPolicyOwner
from app.infrastructure.llm.connection_registry_factory import LLMConnectionAdapter
from app.infrastructure.persistence import PostgresPersistenceRuntime
from app.infrastructure.persistence.goal_binding import CoreGoalPersistenceBinding
from app.infrastructure.persistence.memory_binding import CoreMemoryPersistenceBinding
from app.infrastructure.scheduling import CancellationToken, RuntimeClock, SystemRuntimeClock
from app.usecases.accepted_inputs import CoreAcceptedInputStore
from app.usecases.brain_integration_runtime import BrainIntegrationRuntime, BrainIntegrationWork
from app.usecases.input_meaning import InputMeaningInterpreter
from app.usecases.lifecycle import ApplicationLifecycle, DependencyRetryPolicy
from app.usecases.ports.llm import LLMRolePort

if TYPE_CHECKING:
    from app.composition.speech_deployment import SpeechDeploymentRegistry


@dataclass(frozen=True, slots=True)
class InputMeaningBrainWorkPayload:
    """既存所有者の入力だけを運び、要求時刻と追跡識別子は重複させない。"""

    event: NormalizedInputEvent
    reference_context: ReferenceContext
    request_id: str
    admission: InputAdmission | None = None


class InputMeaningBrainModulePort:
    """固定入力の自己整合を検査し、意味の採用は既存所有者へ委譲する。"""

    def __init__(
        self, interpreter: InputMeaningInterpreter, inputs: CoreAcceptedInputStore | None = None
    ) -> None:
        self._interpreter = interpreter
        self.inputs = inputs

    @staticmethod
    def _validate(work: BrainIntegrationWork) -> InputMeaningBrainWorkPayload:
        payload = work.payload
        if (
            not isinstance(payload, InputMeaningBrainWorkPayload)
            or not isinstance(payload.event, NormalizedInputEvent)
            or not isinstance(payload.reference_context, ReferenceContext)
            or not isinstance(payload.request_id, str)
            or not payload.request_id.strip()
        ):
            raise ValueError("入力意味解析の構成入力が不正です")
        event = payload.event.envelope
        if (
            work.module is not BrainIntegrationModule.INPUT_MEANING
            or work.lane is not BrainIntegrationLane.FOREGROUND_INTERACTION
            or work.envelope.source_event_ids != (event.event_id,)
            or work.envelope.source_context_revision != event.revisions.source_context_revision
            or work.envelope.source_context_revision
            != payload.reference_context.source_context_revision
            or work.envelope.trace_id != event.trace_id
        ):
            raise ValueError("入力意味解析の構成入力の識別子または世代が一致しません")
        return payload

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        self._validate(work)
        return True

    async def execute(
        self,
        work: BrainIntegrationWork,
        cancellation: CancellationToken,
    ) -> InputMeaningInterpretationResult:
        payload = self._validate(work)
        if cancellation.cancelled:
            raise asyncio.CancelledError
        task = asyncio.create_task(
            self._interpreter.interpret(
                payload.event,
                payload.reference_context,
                request_id=payload.request_id,
                trace_id=work.envelope.trace_id,
                created_at=work.envelope.created_at,
            )
        )
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            try:
                await _reap_cleanup(task)
            except (asyncio.CancelledError, Exception):
                pass
            raise

        if cancellation.cancelled:
            raise asyncio.CancelledError
        if self.inputs is not None and result.meaning is not None:
            self.inputs.retain(payload.event, result)
        return result


class UnavailableInputMeaningLiveContextPort:
    """未接続の現在世代を捏造せず、既存の取得失敗境界へ通知する。"""

    async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
        raise RuntimeError("現在の入力文脈の権威ある世代は未接続です")


@dataclass(frozen=True, slots=True)
class CoreComponents:
    """構成済みの値とPort。起動・停止の状態は保持しない。"""

    config: CoreConfig
    character_definition: CharacterDefinitionDocument
    lifecycle: ApplicationLifecycle
    brain: BrainIntegrationRuntime
    interpreter: InputMeaningInterpreter
    bridge: InputMeaningBrainModulePort
    llm: LLMRolePort
    goals: GoalCommitmentStore | CoreGoalPersistenceBinding
    activities: ActivityExecutionAuthority
    input_context: CoreInputReferenceContextBinding
    runtime_subject_identity: RuntimeSubjectIdentity
    memory: CoreMemoryPersistenceBinding | None = None
    cognition: CoreCognitionDelivery | None = None


async def start_core(components: CoreComponents) -> None:
    """構成済みの主要作業系を開始する。"""
    await components.brain.start()
    try:
        if components.cognition is not None and components.cognition.autonomy is not None:
            components.cognition.autonomy.start()
    except BaseException:
        await components.brain.stop()
        raise


async def stop_core(components: CoreComponents) -> None:
    """構成済みの主要作業系を停止し、依存先を回収する。"""
    try:
        try:
            await components.brain.stop()
        finally:
            if components.cognition is not None and components.cognition.speech is not None:
                await components.cognition.speech.close()
    finally:
        try:
            if components.cognition is not None and components.cognition.reflection is not None:
                await components.cognition.reflection.close()
        finally:
            await _close_core_memory(components)


async def _close_core_memory(components: CoreComponents) -> None:
        try:
            if components.memory is not None:
                try:
                    await asyncio.wait_for(
                        components.memory.close(),
                        components.config.shutdown_policy.final_persistence_grace_seconds,
                    )
                except asyncio.TimeoutError:
                    raise ApplicationShutdownError(
                        (
                            ApplicationShutdownFailure(
                                ApplicationShutdownStage.FINAL_PERSISTENCE, "TimeoutError"
                            ),
                        )
                    ) from None
        finally:
            # 前段が失敗してもDB・再接続処理を回収する。
            await components.lifecycle.close()


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


_CleanupResult = TypeVar("_CleanupResult")


async def _reap_cleanup(task: asyncio.Task[_CleanupResult]) -> None:
    """呼出し側の再取消でも所有する終了処理を最後まで回収する。"""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    task.result()


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


def _compose_core(
    config: CoreConfig,
    character: CharacterDefinitionDocument,
    llm: LLMRolePort,
    goals: GoalCommitmentStore | CoreGoalPersistenceBinding,
    memory: CoreMemoryPersistenceBinding | None = None,
    lifecycle: ApplicationLifecycle | None = None,
    cognition: CoreCognitionConfiguration | None = None,
    *,
    prepared_activities: ActivityExecutionAuthority | None = None,
    prepared_context: CoreInputReferenceContextBinding | None = None,
    prepared_clock: RuntimeClock | None = None,
) -> CoreComponents:
    from app.composition.execution_observation import SPEECH_OBSERVATION_POLICY

    activities = prepared_activities or (
        ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
        if cognition is not None and cognition.speech is not None
        else ActivityExecutionAuthority()
    )
    input_context = prepared_context or CoreInputReferenceContextBinding(
        goals, activities, config.input_meaning_policy, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
    )
    interpreter = InputMeaningInterpreter(
        llm,
        input_context,
        config.input_meaning_policy,
    )
    bridge = InputMeaningBrainModulePort(
        interpreter,
        CoreAcceptedInputStore(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_source_event_refs),
    )
    clock = prepared_clock or SystemRuntimeClock()
    lifecycle = lifecycle or ApplicationLifecycle(clock, config.shutdown_policy)
    brain = BrainIntegrationRuntime(clock, config.integration_policy)
    delivery = None
    if cognition is None:
        brain.register_module(BrainIntegrationModule.INPUT_MEANING, bridge)
    else:
        assert bridge.inputs is not None
        delivery = cognition.compose(
            brain, input_context, bridge.inputs, llm, clock, memory, goals
        )
        delivery.register(bridge)
    return CoreComponents(
        config,
        character,
        lifecycle,
        brain,
        interpreter,
        bridge,
        llm,
        goals,
        activities,
        input_context,
        RuntimeSubjectIdentity(
            self_subject_ref=character.character_id,
            character_id=character.character_id,
            character_schema_version=character.schema_version,
            character_definition_revision=character.definition_revision,
        ),
        memory,
        delivery,
    )


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
        await start_core(app)
        print("本体の実行構成が起動しました。", flush=True)
        await stop_requested.wait()
    finally:
        try:
            await stop_core(app)
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
