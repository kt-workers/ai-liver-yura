"""模擬操作先を使い、既存ゲーム実行基盤の独立進行を検証する。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.domain.contracts.common import freeze_json
from app.domain.llm import LLMInterruptibility, LLMPriority
from app.subsystems.game_skill.contracts import (
    GameActionEffectState,
    GameActionExecutionStatus,
    GameActionReport,
    GameFrameAction,
    GameSessionIntent,
)
from app.subsystems.game_skill.runtime import GameSessionState, GameSkillRuntime

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext


def game_fixture() -> ValidationFixture:
    return ValidationFixture(
        "game-independent-loop",
        "1",
        freeze_json(
            {
                "required_applied_frames": 3,
                "interval_seconds": 0.01,
                "session_request_id": "validation-game",
                "decision_id": "fixture-decision",
                "activity_id": "fixture-activity",
                "game_capability_id": "fixture-controller",
                "participant_refs": ["fixture-player"],
                "goal_id": "fixture-goal",
                "goal_revision": 1,
                "strategy_revision": 1,
                "high_level_goal_ref": "fixture-goal",
                "high_level_strategy": {},
                "source_context_revision": 1,
                "priority": "foreground",
                "interruptibility": "interruptible",
                "stream_context_ref": None,
                "created_at": "2026-09-06T00:00:00+00:00",
            }
        ),
        freeze_json(
            {
                "scenario": "別処理の待機中に模擬ゲームの操作が3回適用されることを確認する",
                "external_effect": "模擬操作先のみ。実ゲームの評価ではない",
            }
        ),
    )


def game_target(provenance: ProductionTargetProvenance) -> LabTarget:
    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        if fixture != game_fixture():
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        now = datetime(2026, 9, 6, tzinfo=timezone.utc)
        started, release, applied = asyncio.Event(), asyncio.Event(), asyncio.Event()
        reports: list[GameActionReport] = []
        actions: list[GameFrameAction] = []
        while_waiting: list[bool] = []

        class Controller:
            async def apply(self, action: GameFrameAction) -> GameActionReport:
                async def apply() -> GameActionReport:
                    report = GameActionReport(
                        action.action_id,
                        action.session_id,
                        GameActionExecutionStatus.SUCCEEDED,
                        GameActionEffectState.APPLIED,
                        now,
                        action.game_state_revision + 1,
                    )
                    actions.append(action)
                    reports.append(report)
                    while_waiting.append(started.is_set() and not release.is_set())
                    if len(reports) >= 3:
                        applied.set()
                    return report

                return await context.stage("game.controller", apply)

        class TacticalPolicy:
            async def select(self, state: GameSessionState) -> GameFrameAction | None:
                if applied.is_set():
                    return None
                return GameFrameAction(
                    f"frame:{state.game_state_revision}",
                    state.session_id,
                    state.game_state_revision,
                    state.strategy_revision,
                    "fixture-operation",
                    {},
                    now,
                )

        runtime = GameSkillRuntime(Controller(), TacticalPolicy(), clock=lambda: now)
        intent = GameSessionIntent(
            "validation-game",
            "fixture-decision",
            "fixture-activity",
            "fixture-controller",
            ("fixture-player",),
            "fixture-goal",
            1,
            1,
            "fixture-goal",
            {},
            1,
            LLMPriority.FOREGROUND,
            LLMInterruptibility.INTERRUPTIBLE,
            now,
        )
        runtime.admit(intent)
        runtime.activate(intent.session_request_id)

        async def slow_peer() -> object:
            started.set()
            await release.wait()
            return None

        try:
            context.spawn("waiting-peer", slow_peer)
            await started.wait()
            runtime.start_loop(intent.session_request_id, interval_seconds=0.01)
            await applied.wait()
        finally:
            await runtime.shutdown()
            release.set()
        await context.settle()
        intervals = [x for x in context.intervals if x.iteration == context.iteration]
        waiting = next(x for x in intervals if x.stage == "waiting-peer")
        controller = [x for x in intervals if x.stage == "game.controller"]
        passed = (
            len(reports) == 3
            and all(while_waiting)
            and all(waiting.overlaps(x) for x in controller)
            and runtime.pending_task_count == 0
        )
        return TargetObservation(
            RunStatus.COMPLETED,
            Gate.PASS if passed else Gate.FAIL,
            freeze_json(
                {
                    "actions": [
                        {
                            "action_id": x.action_id,
                            "session_id": x.session_id,
                            "game_state_revision": x.game_state_revision,
                            "strategy_revision": x.strategy_revision,
                            "action_kind": x.action_kind,
                            "parameters": x.parameters,
                            "intended_at": x.intended_at.isoformat(),
                            "deadline_at": None
                            if x.deadline_at is None
                            else x.deadline_at.isoformat(),
                        }
                        for x in actions
                    ],
                    "reports": [
                        {
                            "action_id": x.action_id,
                            "session_id": x.session_id,
                            "status": x.status.value,
                            "effect_state": x.effect_state.value,
                            "applied_at": None
                            if x.applied_at is None
                            else x.applied_at.isoformat(),
                            "game_state_revision_after": x.game_state_revision_after,
                            "sanitized_diagnostics": list(x.sanitized_diagnostics),
                        }
                        for x in reports
                    ],
                    "pending_game_tasks": runtime.pending_task_count,
                }
            ),
        )

    return LabTarget("game_skill", "1", frozenset({LabMode.ISOLATION}), (), provenance, run)
