"""版付き設定と既存所有者を結合し、最小Coreを起動・停止する。"""

from __future__ import annotations

import asyncio
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm.production import create_openai_port_from_environment
from app.config.minimum_brain import MinimumBrainProductionConfig, load_minimum_brain_config
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
)
from app.domain.character.contracts import CharacterDefinitionDocument
from app.domain.input_gateway import NormalizedInputEvent
from app.domain.input_meaning import (
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    InputMeaningInterpreter,
    ReferenceContext,
)
from app.domain.input_meaning.interpreter import descriptor
from app.runtime.kernel import CancellationToken, SystemRuntimeClock
from app.runtime.lifecycle import RuntimeLifecycle
from app.usecases.ports.llm import LLMRolePort


@dataclass(frozen=True, slots=True)
class InputMeaningBrainWorkPayload:
    """既存所有者の入力だけを運び、要求時刻と追跡識別子は重複させない。"""

    event: NormalizedInputEvent
    reference_context: ReferenceContext
    request_id: str


class InputMeaningBrainModulePort:
    """固定入力の自己整合を検査し、意味の採用は既存所有者へ委譲する。"""

    def __init__(self, interpreter: InputMeaningInterpreter) -> None:
        self._interpreter = interpreter

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
        return await self._interpreter.interpret(
            payload.event,
            payload.reference_context,
            request_id=payload.request_id,
            trace_id=work.envelope.trace_id,
            created_at=work.envelope.created_at,
        )


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

    async def start(self) -> None:
        await self.brain.start()

    async def stop(self) -> None:
        try:
            await self.brain.stop()
        finally:
            # 実行基盤の停止失敗でも後段を閉じ、例外は呼出元へ伝播する。
            await self.lifecycle.close()


def build_minimum_core(config_path: Path | None = None) -> MinimumCoreApplication:
    """本番設定を読み、提供サービスの構成不備は既存契約のまま伝える。"""
    root = Path(__file__).resolve().parent.parent
    path = (
        config_path if config_path is not None else root / "resources/config/v2/minimum_brain.yaml"
    )
    config = load_minimum_brain_config(path.read_bytes())
    character = load_character_definition_yaml(
        (root / config.character_definition_path).read_bytes()
    )
    llm = create_openai_port_from_environment((descriptor(config.input_meaning_policy),))
    interpreter = InputMeaningInterpreter(
        llm,
        UnavailableInputMeaningLiveContextPort(),
        config.input_meaning_policy,
    )
    bridge = InputMeaningBrainModulePort(interpreter)
    clock = SystemRuntimeClock()
    lifecycle = RuntimeLifecycle(clock, config.shutdown_policy)
    brain = BrainIntegrationRuntime(clock, config.integration_policy)
    brain.register_module(BrainIntegrationModule.INPUT_MEANING, bridge)
    return MinimumCoreApplication(config, character, lifecycle, brain, interpreter, bridge, llm)


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
