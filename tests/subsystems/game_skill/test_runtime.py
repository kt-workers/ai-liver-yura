from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.llm import LLMInterruptibility, LLMPriority
from app.subsystems.game_skill.contracts import (
    GameActionEffectState,
    GameActionExecutionStatus,
    GameActionReport,
    GameFrameAction,
    GameObservationCategory,
    GameObservationEvent,
    GameSessionIntent,
    GameStrategyUpdate,
)
from app.subsystems.game_skill.runtime import GameSessionState, GameSkillRuntime

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def intent() -> GameSessionIntent:
    return GameSessionIntent(
        "session:1",
        "decision:1",
        "activity:1",
        "cap:game",
        ("user:1",),
        "goal:1",
        3,
        1,
        "goal-ref:1",
        {"mode": "win"},
        8,
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        NOW,
    )


class Controller:
    async def apply(self, action: GameFrameAction) -> GameActionReport:
        return GameActionReport(
            action.action_id,
            action.session_id,
            GameActionExecutionStatus.SUCCEEDED,
            GameActionEffectState.APPLIED,
            NOW,
            action.game_state_revision + 1,
        )


class Policy:
    async def select(self, state: GameSessionState) -> GameFrameAction | None:
        return GameFrameAction(
            "action:1",
            state.session_id,
            state.game_state_revision,
            state.strategy_revision,
            "press",
            {"button": "a"},
            NOW,
        )


class StalePolicy:
    async def select(self, state: GameSessionState) -> GameFrameAction | None:
        return GameFrameAction(
            "action:stale",
            state.session_id,
            state.game_state_revision,
            state.strategy_revision - 1,
            "press",
            {"button": "a"},
            NOW,
        )


def test_session_strategy_and_selected_vs_applied_action_are_typed() -> None:
    async def scenario() -> None:
        runtime = GameSkillRuntime(Controller(), Policy(), observation_limit=1)
        runtime.admit(intent())
        runtime.activate("session:1")
        report = await runtime.tick("session:1")
        assert report is not None and report.effect_state is GameActionEffectState.APPLIED
        assert runtime.snapshot("session:1").game_state_revision == 1
        updated = runtime.apply_strategy(
            GameStrategyUpdate(
                "strategy:2", "session:1", "goal:1", 3, 2, {"mode": "defend"}, "decision:2", NOW
            )
        )
        assert updated.strategy_revision == 2
        runtime.pause("session:1")
        assert await runtime.tick("session:1") is None
        with pytest.raises(ValueError, match="Goal revision"):
            runtime.apply_strategy(
                GameStrategyUpdate("strategy:3", "session:1", "goal:1", 2, 3, {}, "decision:3", NOW)
            )
        await runtime.stop("session:1", cancelled=True)
        assert runtime.snapshot("session:1").lifecycle.value == "cancelled"

    asyncio.run(scenario())


def test_stale_tactical_action_is_discarded_before_controller_effect() -> None:
    class RecordingController(Controller):
        def __init__(self) -> None:
            self.calls = 0

        async def apply(self, action: GameFrameAction) -> GameActionReport:
            self.calls += 1
            return await super().apply(action)

    async def scenario() -> None:
        controller = RecordingController()
        runtime = GameSkillRuntime(controller, StalePolicy())
        runtime.admit(intent())
        runtime.activate("session:1")
        assert await runtime.tick("session:1") is None
        assert controller.calls == 0

    asyncio.run(scenario())


def test_pause_during_selection_prevents_controller_apply() -> None:
    class WaitingPolicy(Policy):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def select(self, state: GameSessionState) -> GameFrameAction:
            self.started.set()
            await self.release.wait()
            action = await super().select(state)
            assert action is not None
            return action

    class RecordingController(Controller):
        def __init__(self) -> None:
            self.calls = 0

        async def apply(self, action: GameFrameAction) -> GameActionReport:
            self.calls += 1
            return await super().apply(action)

    async def scenario() -> None:
        policy = WaitingPolicy()
        controller = RecordingController()
        runtime = GameSkillRuntime(controller, policy)
        runtime.admit(intent())
        runtime.activate("session:1")
        pending = asyncio.create_task(runtime.tick("session:1"))
        await policy.started.wait()
        runtime.pause("session:1")
        policy.release.set()
        assert await pending is None
        assert controller.calls == 0

    asyncio.run(scenario())


def test_strategy_update_during_controller_wait_keeps_new_strategy_and_marks_report_stale() -> None:
    class WaitingController(Controller):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def apply(self, action: GameFrameAction) -> GameActionReport:
            self.started.set()
            await self.release.wait()
            return await super().apply(action)

    async def scenario() -> None:
        controller = WaitingController()
        runtime = GameSkillRuntime(controller, Policy())
        runtime.admit(intent())
        runtime.activate("session:1")
        pending = asyncio.create_task(runtime.tick("session:1"))
        await controller.started.wait()
        runtime.apply_strategy(
            GameStrategyUpdate("strategy:2", "session:1", "goal:1", 3, 2, {}, "decision:2", NOW)
        )
        controller.release.set()
        report = await pending
        assert report is not None and report.status is GameActionExecutionStatus.STALE
        assert runtime.snapshot("session:1").strategy_revision == 2
        assert runtime.snapshot("session:1").game_state_revision == 1

    asyncio.run(scenario())


def test_stale_failed_controller_report_is_returned_with_ambiguous_effect_truth() -> None:
    class WaitingFailedController(Controller):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def apply(self, action: GameFrameAction) -> GameActionReport:
            self.started.set()
            await self.release.wait()
            return GameActionReport(
                action.action_id,
                action.session_id,
                GameActionExecutionStatus.FAILED,
                GameActionEffectState.NOT_APPLIED,
                None,
                None,
            )

    async def scenario() -> None:
        controller = WaitingFailedController()
        runtime = GameSkillRuntime(controller, Policy())
        runtime.admit(intent())
        runtime.activate("session:1")
        pending = asyncio.create_task(runtime.tick("session:1"))
        await controller.started.wait()
        runtime.apply_strategy(
            GameStrategyUpdate("strategy:2", "session:1", "goal:1", 3, 2, {}, "decision:2", NOW)
        )
        controller.release.set()
        report = await pending
        assert report is not None
        assert report.status is GameActionExecutionStatus.STALE
        assert report.effect_state is GameActionEffectState.AMBIGUOUS
        assert "STALE_AFTER_CONTROLLER" in report.sanitized_diagnostics

    asyncio.run(scenario())


def test_action_deadline_timeout_keeps_effect_ambiguous() -> None:
    class SlowController(Controller):
        async def apply(self, action: GameFrameAction) -> GameActionReport:
            await asyncio.Event().wait()
            raise AssertionError("deadline must cancel controller await")

    class DeadlinePolicy(Policy):
        async def select(self, state: GameSessionState) -> GameFrameAction:
            return GameFrameAction(
                "action:deadline",
                state.session_id,
                state.game_state_revision,
                state.strategy_revision,
                "press",
                {},
                NOW,
                NOW + timedelta(milliseconds=1),
            )

    async def scenario() -> None:
        runtime = GameSkillRuntime(SlowController(), DeadlinePolicy(), clock=lambda: NOW)
        runtime.admit(intent())
        runtime.activate("session:1")
        report = await runtime.tick("session:1")
        assert report is not None and report.status is GameActionExecutionStatus.TIMED_OUT
        assert report.effect_state is GameActionEffectState.AMBIGUOUS
        assert runtime.metrics.deadline_miss_count == 1
        assert runtime.metrics.pending_loop_count == 0

    asyncio.run(scenario())


def test_observations_are_bounded_and_no_raw_conversation_contract_exists() -> None:
    runtime = GameSkillRuntime(Controller(), Policy(), observation_limit=1)
    runtime.admit(intent())
    for event_id in ("event:1", "event:2"):
        runtime.publish_observation(
            GameObservationEvent(
                event_id,
                "session:1",
                GameObservationCategory.DANGER_OR_OPPORTUNITY,
                0.8,
                ("opponent:1",),
                0,
                NOW,
                {"hp": 1},
            )
        )
    assert [event.event_id for event in runtime.drain_observations()] == ["event:2"]


def test_realtime_loop_has_bounded_cadence_and_shutdown_cancels_its_own_task() -> None:
    class SlowPolicy:
        async def select(self, state: GameSessionState) -> GameFrameAction | None:
            await asyncio.Event().wait()
            return None

    async def scenario() -> None:
        runtime = GameSkillRuntime(Controller(), SlowPolicy())
        runtime.admit(intent())
        runtime.activate("session:1")
        runtime.start_loop("session:1", interval_seconds=0.001)
        await asyncio.sleep(0.004)
        assert runtime.pending_task_count == 1
        await runtime.shutdown()
        assert runtime.pending_task_count == 0
        assert runtime.snapshot("session:1").lifecycle.value == "cancelled"

    asyncio.run(scenario())


def test_shutdown_during_controller_wait_finishes_and_retains_ambiguous_effect_evidence() -> None:
    class WaitingController(Controller):
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def apply(self, action: GameFrameAction) -> GameActionReport:
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled controllerは完了しません")

    async def scenario() -> None:
        controller = WaitingController()
        runtime = GameSkillRuntime(controller, Policy())
        runtime.admit(intent())
        runtime.activate("session:1")
        runtime.start_loop("session:1", interval_seconds=1)
        await controller.started.wait()

        await asyncio.wait_for(runtime.shutdown(), timeout=0.1)

        reports = runtime.drain_interrupted_reports()
        assert runtime.pending_task_count == 0
        assert runtime.snapshot("session:1").lifecycle.value == "cancelled"
        assert reports[0].status is GameActionExecutionStatus.CANCELLED
        assert reports[0].effect_state is GameActionEffectState.AMBIGUOUS

    asyncio.run(scenario())


def test_concurrent_ticks_are_session_local_single_flight_and_bind_each_effect_to_live_revision(
) -> None:
    class RecordingController(Controller):
        def __init__(self) -> None:
            self.revisions: list[int] = []

        async def apply(self, action: GameFrameAction) -> GameActionReport:
            self.revisions.append(action.game_state_revision)
            await asyncio.sleep(0)
            return await super().apply(action)

    async def scenario() -> None:
        controller = RecordingController()
        runtime = GameSkillRuntime(controller, Policy())
        runtime.admit(intent())
        runtime.activate("session:1")

        first, second = await asyncio.gather(
            runtime.tick("session:1"),
            runtime.tick("session:1"),
        )

        assert first is not None and second is not None
        assert controller.revisions == [0, 1]
        assert runtime.snapshot("session:1").game_state_revision == 2

    asyncio.run(scenario())
