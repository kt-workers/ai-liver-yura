"""本番ゲーム実行基盤のリビジョン・観測上限・終了を、明示した入力列から記録する。"""

import asyncio
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import timedelta
from math import isfinite
from time import monotonic_ns
from typing import cast

from app.domain.contracts.common import JsonValue, freeze_json
from app.subsystems.game_skill.contracts import (
    GameObservationEvent,
    GameSessionIntent,
    GameStrategyUpdate,
)
from app.subsystems.game_skill.runtime import (
    GameControllerPort,
    GameSkillRuntime,
    GameTacticalPolicy,
)

from .body import _encode
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    positive,
)
from .runtime import LabTarget, RunContext


def _encode_public(value: object) -> object:
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and type(value).__module__.startswith(
            ("app.subsystems.game_skill.", "app.subsystems.validation.game_monitor")
        )
    ):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    return _encode(value)


def _project(value: object) -> JsonValue:
    return freeze_json(
        cast(JsonValue, json.loads(json.dumps(value, default=_encode_public, allow_nan=False)))
    )


@dataclass(frozen=True)
class GameMonitorFrame:
    observations: tuple[GameObservationEvent, ...] = ()
    strategy: GameStrategyUpdate | None = None

    def __post_init__(self) -> None:
        observations = tuple(self.observations)
        if any(not isinstance(item, GameObservationEvent) for item in observations):
            raise ValueError("ゲーム観測には本番の型付き入力が必要です")
        if self.strategy is not None and not isinstance(self.strategy, GameStrategyUpdate):
            raise ValueError("戦略更新には本番の型付き入力が必要です")
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True)
class GameMonitorCase:
    fixture: ValidationFixture
    intent: GameSessionIntent
    frames: tuple[GameMonitorFrame, ...]
    sample_interval_s: float
    loop_interval_s: float
    observation_limit: int
    cancel_at_end: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.intent, GameSessionIntent):
            raise ValueError("ゲーム開始には本番の型付き要求が必要です")
        frames = tuple(self.frames)
        if not frames or any(not isinstance(item, GameMonitorFrame) for item in frames):
            raise ValueError("ゲーム監視には1件以上の入力区間が必要です")
        for value in (self.sample_interval_s, self.loop_interval_s):
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError("監視とゲーム更新の間隔は有限の正数で指定してください")
        positive(self.observation_limit)
        if type(self.cancel_at_end) is not bool:
            raise ValueError("終了時の取消指定は真偽値で指定してください")
        object.__setattr__(self, "frames", frames)

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                field.name: getattr(self, field.name)
                for field in fields(self)
                if field.name != "fixture"
            }
        )


def game_monitor_target(
    cases: tuple[GameMonitorCase, ...],
    controller: GameControllerPort,
    tactical_policy: GameTacticalPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("ゲーム監視の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        if len(case.frames) + 3 > context.policy.max_intervals:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        started_ns = monotonic_ns()
        owner = GameSkillRuntime(
            controller,
            tactical_policy,
            observation_limit=case.observation_limit,
            clock=lambda: (
                case.intent.created_at
                + timedelta(seconds=(monotonic_ns() - started_ns) / 1_000_000_000)
            ),
        )
        context.add_cleanup("game.monitor_runtime", owner.shutdown)
        session_id = case.intent.session_request_id

        async def start() -> None:
            owner.admit(case.intent)
            owner.activate(session_id)
            owner.start_loop(session_id, interval_seconds=case.loop_interval_s)

        await context.invoke_product("game.start", start)
        samples: list[dict[str, object]] = []
        status = RunStatus.COMPLETED
        for index, frame in enumerate(case.frames):

            async def sample(item: GameMonitorFrame = frame) -> dict[str, object]:
                before = owner.snapshot(session_id)
                if item.strategy is not None:
                    owner.apply_strategy(item.strategy)
                for event in item.observations:
                    owner.publish_observation(event)
                await asyncio.sleep(case.sample_interval_s)
                return {
                    "before": before,
                    "after": owner.snapshot(session_id),
                    "observations": owner.drain_observations(),
                    "submitted_observations": len(item.observations),
                    "metrics": owner.metrics,
                    "sampled_ns": monotonic_ns(),
                }

            row = await context.invoke_product("game.monitor_sample", sample)
            row["index"] = index
            samples.append(row)
            # 観測期間の途中で専用処理が終了した場合は、監視成功へ読み替えない。
            if owner.pending_task_count == 0:
                status = RunStatus.PRODUCT_FAILED
                break
        before_stop = owner.snapshot(session_id)
        stop_started_ns = monotonic_ns()

        async def stop() -> None:
            await owner.stop(session_id, cancelled=case.cancel_at_end)

        await context.invoke_product("game.stop", stop)
        stopped_ns = monotonic_ns()
        return TargetObservation(
            status,
            Gate.NOT_RUN,
            _project(
                {
                    "samples": samples,
                    "before_stop": before_stop,
                    "after_stop": owner.snapshot(session_id),
                    "started_ns": started_ns,
                    "stop_started_ns": stop_started_ns,
                    "stopped_ns": stopped_ns,
                    "stop_elapsed_ns": stopped_ns - stop_started_ns,
                    "interrupted_reports": owner.drain_interrupted_reports(),
                    "pending_game_tasks": owner.pending_task_count,
                    "metrics": owner.metrics,
                }
            ),
        )

    return LabTarget(
        "game_monitor", contract_revision, frozenset({LabMode.ISOLATION}), (), provenance, run
    )
