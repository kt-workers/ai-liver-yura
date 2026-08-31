from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol

from app.domain.contracts.common import JsonValue
from app.subsystems.game_skill.contracts import (
    GameActionEffectState,
    GameActionExecutionStatus,
    GameActionReport,
    GameFrameAction,
    GameObservationEvent,
    GameSessionIntent,
    GameSessionLifecycle,
    GameStrategyUpdate,
)


class GameControllerPort(Protocol):
    async def apply(self, action: GameFrameAction) -> GameActionReport: ...


class GameTacticalPolicy(Protocol):
    async def select(self, session: GameSessionState) -> GameFrameAction | None: ...


@dataclass(frozen=True, slots=True)
class GameSessionState:
    session_id: str
    intent: GameSessionIntent
    lifecycle: GameSessionLifecycle
    game_state_revision: int
    strategy_revision: int
    strategy_payload: JsonValue


@dataclass(frozen=True, slots=True)
class GameRuntimeMetrics:
    deadline_miss_count: int
    pending_loop_count: int

    def __post_init__(self) -> None:
        if (
            type(self.deadline_miss_count) is not int
            or type(self.pending_loop_count) is not int
            or self.deadline_miss_count < 0
            or self.pending_loop_count < 0
        ):
            raise ValueError("runtime metricsが不正です")


class GameSkillRuntime:
    """専用frame lane。CoreのGoal/Attentionを変更せず、bounded eventだけを返す。"""

    def __init__(
        self,
        controller: GameControllerPort,
        tactical_policy: GameTacticalPolicy,
        *,
        observation_limit: int = 32,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(observation_limit) is not int or observation_limit < 1:
            raise ValueError("observation_limit が不正です")
        self._controller = controller
        self._tactical_policy = tactical_policy
        self._states: dict[str, GameSessionState] = {}
        self._observations: deque[GameObservationEvent] = deque(maxlen=observation_limit)
        self._interrupted_reports: deque[GameActionReport] = deque(maxlen=observation_limit)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._tick_locks: dict[str, asyncio.Lock] = {}
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._deadline_miss_count = 0

    def admit(self, intent: GameSessionIntent) -> GameSessionState:
        if intent.session_request_id in self._states:
            raise ValueError("sessionが重複しています")
        state = GameSessionState(
            intent.session_request_id,
            intent,
            GameSessionLifecycle.ADMITTED,
            0,
            intent.strategy_revision,
            intent.high_level_strategy,
        )
        self._states[state.session_id] = state
        self._tick_locks[state.session_id] = asyncio.Lock()
        return state

    def activate(self, session_id: str) -> GameSessionState:
        state = self._require(session_id)
        if state.lifecycle not in (GameSessionLifecycle.ADMITTED, GameSessionLifecycle.PAUSED):
            raise ValueError("session lifecycleが不正です")
        updated = GameSessionState(
            state.session_id,
            state.intent,
            GameSessionLifecycle.ACTIVE,
            state.game_state_revision,
            state.strategy_revision,
            state.strategy_payload,
        )
        self._states[session_id] = updated
        return updated

    def pause(self, session_id: str) -> GameSessionState:
        state = self._require(session_id)
        if state.lifecycle is not GameSessionLifecycle.ACTIVE:
            raise ValueError("active sessionだけをpauseできます")
        updated = GameSessionState(
            state.session_id,
            state.intent,
            GameSessionLifecycle.PAUSED,
            state.game_state_revision,
            state.strategy_revision,
            state.strategy_payload,
        )
        self._states[session_id] = updated
        return updated

    def apply_strategy(self, update: GameStrategyUpdate) -> GameSessionState:
        state = self._require(update.session_id)
        if (
            update.goal_id != state.intent.goal_id
            or update.expected_goal_revision != state.intent.goal_revision
        ):
            raise ValueError("Goal revisionが現在sessionと一致しません")
        if update.strategy_revision <= state.strategy_revision:
            raise ValueError("strategy revisionが単調増加していません")
        updated = GameSessionState(
            state.session_id,
            state.intent,
            state.lifecycle,
            state.game_state_revision,
            update.strategy_revision,
            update.strategy_payload,
        )
        self._states[update.session_id] = updated
        return updated

    async def tick(self, session_id: str) -> GameActionReport | None:
        async with self._tick_locks[session_id]:
            state = self._require(session_id)
            if state.lifecycle is not GameSessionLifecycle.ACTIVE:
                return None
            action = await self._tactical_policy.select(state)
            if action is None:
                return None
            current = self._require(session_id)
            if (
                action.session_id != session_id
                or action.strategy_revision != current.strategy_revision
                or action.game_state_revision != current.game_state_revision
                or current.lifecycle is not GameSessionLifecycle.ACTIVE
            ):
                return None
            if action.deadline_at is not None and action.deadline_at <= self._now():
                return self._report(
                    action, GameActionExecutionStatus.FAILED, GameActionEffectState.NOT_APPLIED
                )
            try:
                if action.deadline_at is None:
                    report = await self._controller.apply(action)
                else:
                    report = await asyncio.wait_for(
                        self._controller.apply(action),
                        timeout=(action.deadline_at - self._now()).total_seconds(),
                    )
            except asyncio.TimeoutError:
                self._deadline_miss_count += 1
                return self._report(
                    action, GameActionExecutionStatus.TIMED_OUT, GameActionEffectState.AMBIGUOUS
                )
            except asyncio.CancelledError:
                self._interrupted_reports.append(
                    self._report(
                        action,
                        GameActionExecutionStatus.CANCELLED,
                        GameActionEffectState.AMBIGUOUS,
                    )
                )
                raise
            if report.session_id != session_id or report.action_id != action.action_id:
                raise ValueError("controller report identityが不正です")
            live = self._require(session_id)
            if (
                live.strategy_revision != current.strategy_revision
                or live.lifecycle is not current.lifecycle
            ):
                if (
                    report.effect_state is GameActionEffectState.APPLIED
                    and report.game_state_revision_after is not None
                    and report.game_state_revision_after > live.game_state_revision
                ):
                    self._states[session_id] = GameSessionState(
                        live.session_id,
                        live.intent,
                        live.lifecycle,
                        report.game_state_revision_after,
                        live.strategy_revision,
                        live.strategy_payload,
                    )
                # STALE は APPLIED または AMBIGUOUS のeffect truthだけを表せる。
                # controllerの通常失敗は世代交代後に再解釈しない。
                effect_state = (
                    report.effect_state
                    if report.effect_state in (
                        GameActionEffectState.APPLIED,
                        GameActionEffectState.AMBIGUOUS,
                    )
                    else GameActionEffectState.AMBIGUOUS
                )
                return replace(
                    report,
                    status=GameActionExecutionStatus.STALE,
                    effect_state=effect_state,
                    sanitized_diagnostics=(
                        report.sanitized_diagnostics + ("STALE_AFTER_CONTROLLER",)
                    ),
                )
            if report.game_state_revision_after is not None:
                self._states[session_id] = GameSessionState(
                    live.session_id,
                    live.intent,
                    live.lifecycle,
                    report.game_state_revision_after,
                    live.strategy_revision,
                    live.strategy_payload,
                )
            return report

    def _report(
        self,
        action: GameFrameAction,
        status: GameActionExecutionStatus,
        effect_state: GameActionEffectState,
    ) -> GameActionReport:
        return GameActionReport(
            action.action_id,
            action.session_id,
            status,
            effect_state,
            None,
            None,
            (status.value,),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock がaware datetimeを返しません")
        return value

    def start_loop(self, session_id: str, *, interval_seconds: float) -> None:
        """game固有cadenceで動くlaneを開始する。CoreのturnやLLM待ちへ従属しない。"""
        if type(interval_seconds) not in (int, float) or interval_seconds <= 0:
            raise ValueError("interval_seconds が不正です")
        if session_id in self._tasks:
            raise ValueError("session loopが重複しています")
        self._require(session_id)
        self._tasks[session_id] = asyncio.create_task(
            self._run_loop(session_id, float(interval_seconds))
        )

    async def _run_loop(self, session_id: str, interval_seconds: float) -> None:
        loop = asyncio.get_running_loop()
        next_deadline = loop.time()
        try:
            while self._require(session_id).lifecycle in (
                GameSessionLifecycle.ADMITTED,
                GameSessionLifecycle.ACTIVE,
                GameSessionLifecycle.PAUSED,
            ):
                if self._require(session_id).lifecycle is GameSessionLifecycle.ACTIVE:
                    try:
                        next_deadline += interval_seconds
                        await asyncio.wait_for(
                            self.tick(session_id), timeout=max(0.0, next_deadline - loop.time())
                        )
                    except asyncio.TimeoutError:
                        self._deadline_miss_count += 1
                else:
                    next_deadline = loop.time() + interval_seconds
                remaining = next_deadline - loop.time()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                else:
                    next_deadline = loop.time()
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(session_id, None)

    def publish_observation(self, event: GameObservationEvent) -> None:
        state = self._require(event.session_id)
        if event.game_state_revision > state.game_state_revision:
            raise ValueError("future game state revisionは観測できません")
        self._observations.append(event)

    def drain_observations(self) -> tuple[GameObservationEvent, ...]:
        events = tuple(self._observations)
        self._observations.clear()
        return events

    def drain_interrupted_reports(self) -> tuple[GameActionReport, ...]:
        reports = tuple(self._interrupted_reports)
        self._interrupted_reports.clear()
        return reports

    async def stop(self, session_id: str, *, cancelled: bool) -> GameSessionState:
        state = self._require(session_id)
        lifecycle = GameSessionLifecycle.CANCELLED if cancelled else GameSessionLifecycle.ENDED
        updated = GameSessionState(
            state.session_id,
            state.intent,
            lifecycle,
            state.game_state_revision,
            state.strategy_revision,
            state.strategy_payload,
        )
        self._states[session_id] = updated
        task = self._tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return updated

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(self.stop(session_id, cancelled=True) for session_id in tuple(self._states)),
            return_exceptions=True,
        )

    def snapshot(self, session_id: str) -> GameSessionState:
        return self._require(session_id)

    @property
    def pending_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks.values())

    @property
    def metrics(self) -> GameRuntimeMetrics:
        return GameRuntimeMetrics(self._deadline_miss_count, self.pending_task_count)

    def _require(self, session_id: str) -> GameSessionState:
        try:
            return self._states[session_id]
        except KeyError as error:
            raise ValueError("unknown sessionです") from error
