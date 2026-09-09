"""リビジョン付き設定と既存所有者を結合し、最小Coreを起動・停止する。"""

from __future__ import annotations

import asyncio
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm.production import create_openai_port_from_environment
from app.composition.accepted_input import CoreAcceptedInputStore
from app.composition.cognition import CoreCognitionDelivery
from app.composition.cognition_configuration import CoreCognitionConfiguration
from app.composition.goal_persistence import CoreGoalPersistenceBinding
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.config.minimum_brain import MinimumBrainProductionConfig, load_minimum_brain_config
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.appraisal import descriptor as appraisal_descriptor
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.character.contracts import CharacterDefinitionDocument
from app.domain.contracts.common import require_identifier
from app.domain.executive.deliberator import descriptor as executive_descriptor
from app.domain.goals import GoalCommitmentStore
from app.domain.input_gateway import InputAdmission, NormalizedInputEvent
from app.domain.input_meaning import (
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    InputMeaningInterpreter,
    ReferenceContext,
)
from app.domain.input_meaning.interpreter import descriptor
from app.domain.llm import LLMRoleDescriptor
from app.infrastructure.persistence import PostgresPersistenceRuntime
from app.runtime.kernel import CancellationToken, SystemRuntimeClock
from app.runtime.lifecycle import DependencyRetryPolicy, RuntimeLifecycle
from app.runtime.shutdown import RuntimeShutdownError, RuntimeShutdownFailure, RuntimeShutdownStage
from app.usecases.ports.llm import LLMRolePort


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
class MinimumCoreApplication:
    """同一の不変設定に結び付いた最小Coreの構成。"""

    config: MinimumBrainProductionConfig
    character_definition: CharacterDefinitionDocument
    lifecycle: RuntimeLifecycle
    brain: BrainIntegrationRuntime
    interpreter: InputMeaningInterpreter
    bridge: InputMeaningBrainModulePort
    llm: LLMRolePort
    goals: GoalCommitmentStore | CoreGoalPersistenceBinding
    activities: ActivityExecutionAuthority
    input_context: CoreInputReferenceContextBinding
    memory: CoreMemoryPersistenceBinding | None = None
    cognition: CoreCognitionDelivery | None = None
    _stop_task: asyncio.Task[None] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    async def start(self) -> None:
        await self.brain.start()

    async def stop(self) -> None:
        if self._stop_task is None:
            object.__setattr__(self, "_stop_task", asyncio.create_task(self._stop()))
        assert self._stop_task is not None
        await _reap_cleanup(self._stop_task)

    async def _stop(self) -> None:
        try:
            await self.brain.stop()
        finally:
            try:
                if self.memory is not None:
                    try:
                        await asyncio.wait_for(
                            self.memory.close(),
                            self.config.shutdown_policy.final_persistence_grace_seconds,
                        )
                    except asyncio.TimeoutError:
                        raise RuntimeShutdownError(
                            (
                                RuntimeShutdownFailure(
                                    RuntimeShutdownStage.FINAL_PERSISTENCE, "TimeoutError"
                                ),
                            )
                        ) from None
            finally:
                # 前段が失敗してもDB・再接続処理を回収する。
                await self.lifecycle.close()


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


def build_minimum_core(
    config_path: Path | None = None, *, cognition: CoreCognitionConfiguration | None = None
) -> MinimumCoreApplication:
    """本番設定を読み、提供サービスの構成不備は既存契約のまま伝える。"""
    config, character, llm = _load_core(config_path, cognition)
    return _compose_core(config, character, llm, GoalCommitmentStore(), cognition=cognition)


def _load_core(
    config_path: Path | None,
    cognition: CoreCognitionConfiguration | None = None,
) -> tuple[MinimumBrainProductionConfig, CharacterDefinitionDocument, LLMRolePort]:
    root = Path(__file__).resolve().parent.parent
    path = (
        config_path if config_path is not None else root / "resources/config/v2/minimum_brain.yaml"
    )
    config = load_minimum_brain_config(path.read_bytes())
    character = load_character_definition_yaml(
        (root / config.character_definition_path).read_bytes()
    )
    roles: tuple[LLMRoleDescriptor, ...] = (descriptor(config.input_meaning_policy),)
    if cognition is not None:
        roles += (
            appraisal_descriptor(cognition.appraisal_policy),
            executive_descriptor(cognition.executive_policy),
        )
    llm = create_openai_port_from_environment(roles)
    return config, character, llm


def _compose_core(
    config: MinimumBrainProductionConfig,
    character: CharacterDefinitionDocument,
    llm: LLMRolePort,
    goals: GoalCommitmentStore | CoreGoalPersistenceBinding,
    memory: CoreMemoryPersistenceBinding | None = None,
    lifecycle: RuntimeLifecycle | None = None,
    cognition: CoreCognitionConfiguration | None = None,
) -> MinimumCoreApplication:
    activities = ActivityExecutionAuthority()
    input_context = CoreInputReferenceContextBinding(
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
    clock = SystemRuntimeClock()
    lifecycle = lifecycle or RuntimeLifecycle(clock, config.shutdown_policy)
    brain = BrainIntegrationRuntime(clock, config.integration_policy)
    delivery = None
    if cognition is None:
        brain.register_module(BrainIntegrationModule.INPUT_MEANING, bridge)
    else:
        assert bridge.inputs is not None
        delivery = cognition.compose(brain, input_context, bridge.inputs, llm, clock)
        delivery.register(bridge)
    return MinimumCoreApplication(
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
) -> MinimumCoreApplication:
    """明示された保存実行基盤を所有し、復元した目標を本体へ接続する。"""
    if not isinstance(persistence, PostgresPersistenceRuntime):
        raise ValueError("本体の保存構成にはPostgresPersistenceRuntimeが必要です")
    app: MinimumCoreApplication | None = None
    memory: CoreMemoryPersistenceBinding | None = None
    lifecycle: RuntimeLifecycle | None = None
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
        lifecycle = RuntimeLifecycle(SystemRuntimeClock(), config.shutdown_policy)
        persistence.attach(lifecycle, retry_policy)
        await persistence.start()
        goals = await CoreGoalPersistenceBinding.restore(persistence, runtime_epoch=runtime_epoch)
        app = _compose_core(config, character, llm, goals, memory, lifecycle, cognition)
        return app
    except BaseException:

        async def cleanup() -> None:
            try:
                if app is not None:
                    await app.stop()
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


async def run_minimum_core() -> None:
    """停止通知まで待機し、シグナル登録と所有タスクを確実に片付ける。"""
    app = build_minimum_core()
    loop = asyncio.get_running_loop()
    stop_requested = asyncio.Event()
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    registered: list[signal.Signals] = []
    try:
        for signum in previous:
            loop.add_signal_handler(signum, stop_requested.set)
            registered.append(signum)
        await app.start()
        print("最小Coreの起動が完了しました。", flush=True)
        await stop_requested.wait()
    finally:
        try:
            await app.stop()
        finally:
            for signum in registered:
                loop.remove_signal_handler(signum)
                signal.signal(signum, previous[signum])


def main() -> None:
    try:
        asyncio.run(run_minimum_core())
    except (OSError, ValueError, RuntimeError):
        print("最小Coreの起動または停止に失敗しました。", file=sys.stderr)
        raise SystemExit(1) from None
