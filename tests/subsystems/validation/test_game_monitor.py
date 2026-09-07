"""本番のゲーム進行・リビジョンの更新・観測容量・終了回収を検証する。"""

import asyncio
from dataclasses import replace

import pytest

from app.subsystems.game_skill.contracts import (
    GameActionReport,
    GameFrameAction,
    GameObservationCategory,
    GameObservationEvent,
    GameStrategyUpdate,
)
from app.subsystems.validation.contracts import Gate, RunStatus
from app.subsystems.validation.game_monitor import (
    GameMonitorCase,
    GameMonitorFrame,
    game_monitor_target,
)
from app.subsystems.validation.runtime import ValidationRunner
from tests.subsystems.game_skill import test_runtime as product
from tests.subsystems.validation.json_values import array_at, integer_at, value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case(
    frames: tuple[GameMonitorFrame, ...] = (GameMonitorFrame(),),
    *,
    sample_interval_s: float = 0.03,
    loop_interval_s: float = 0.005,
    cancel: bool = False,
) -> GameMonitorCase:
    item = GameMonitorCase(
        FIXTURE, product.intent(), frames, sample_interval_s, loop_interval_s, 4, cancel
    )
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


def runner(item: GameMonitorCase, controller: product.Controller) -> ValidationRunner:
    return ValidationRunner(
        (game_monitor_target((item,), controller, product.Policy(), PROVENANCE, "1"),),
        replace(POLICY, max_export_bytes=500_000),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_burst_and_strategy_update_keep_frames_advancing_then_stop(cancel: bool) -> None:
    events = tuple(
        GameObservationEvent(
            f"observation:{index}",
            "session:1",
            GameObservationCategory.DANGER_OR_OPPORTUNITY,
            0.5,
            (),
            0,
            product.NOW,
            {"index": index},
        )
        for index in range(100)
    )
    update = GameStrategyUpdate(
        "update:1", "session:1", "goal:1", 3, 2, {}, "decision:2", product.NOW
    )
    item = case((GameMonitorFrame(events), GameMonitorFrame(strategy=update)), cancel=cancel)
    owner = runner(item, product.Controller())
    result = await owner.run(replace(spec(), target_module="game_monitor"), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    value = result.stage_results[0].typed_outputs
    samples = array_at(value, "samples")
    assert len(samples) == 2
    assert integer_at(samples[0], "after", "game_state_revision") > 0
    assert integer_at(samples[1], "after", "game_state_revision") > integer_at(
        samples[0], "after", "game_state_revision"
    )
    assert integer_at(samples[1], "after", "strategy_revision") == 2
    assert [value_at(event, "event_id") for event in array_at(samples[0], "observations")] == [
        f"observation:{index}" for index in range(96, 100)
    ]
    assert integer_at(samples[0], "submitted_observations") == 100
    assert value_at(value, "after_stop", "lifecycle") == ("cancelled" if cancel else "ended")
    assert integer_at(value, "pending_game_tasks") == owner.pending_count == 0
    assert integer_at(value, "stop_elapsed_ns") >= 0
    assert result.fixture.typed_inputs == item.typed_inputs()


class SlowController(product.Controller):
    def __init__(self) -> None:
        self.started, self.stopped = asyncio.Event(), asyncio.Event()

    async def apply(self, action: GameFrameAction) -> GameActionReport:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped.set()
        raise AssertionError("取消待機が通常終了しました")


@pytest.mark.asyncio
async def test_stop_retains_uncertain_effect_and_collects_controller() -> None:
    controller = SlowController()
    item = case(loop_interval_s=1, cancel=True)
    owner = runner(item, controller)
    result = await owner.run(replace(spec(), target_module="game_monitor"), item.fixture)
    value = result.stage_results[0].typed_outputs
    assert result.status is RunStatus.COMPLETED
    assert controller.started.is_set() and controller.stopped.is_set()
    reports = array_at(value, "interrupted_reports")
    assert len(reports) == 1
    assert value_at(reports[0], "status") == "cancelled"
    assert value_at(reports[0], "effect_state") == "ambiguous"
    assert integer_at(value, "pending_game_tasks") == owner.pending_count == 0


@pytest.mark.asyncio
async def test_external_cancel_collects_game_loop_during_observation() -> None:
    controller = SlowController()
    item = case(sample_interval_s=10, loop_interval_s=10)
    owner = runner(item, controller)
    run_spec = replace(spec(), target_module="game_monitor")
    task = asyncio.create_task(owner.run(run_spec, item.fixture))
    await asyncio.wait_for(controller.started.wait(), 0.5)
    await owner.cancel(run_spec.run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert controller.stopped.is_set() and owner.pending_count == 0


@pytest.mark.asyncio
async def test_invalid_strategy_is_product_failure_and_not_rewritten() -> None:
    update = GameStrategyUpdate(
        "update:1", "session:1", "goal:1", 2, 2, {}, "decision:2", product.NOW
    )
    item = case((GameMonitorFrame(strategy=update),))
    owner = runner(item, product.Controller())
    result = await owner.run(replace(spec(), target_module="game_monitor"), item.fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert result.machine_gate is Gate.NOT_RUN and owner.pending_count == 0


@pytest.mark.asyncio
async def test_mismatched_input_and_excess_sample_count_do_not_start_controller() -> None:
    for item, fixture in (
        (case(), FIXTURE),
        (case((GameMonitorFrame(),) * 16), None),
    ):
        controller = SlowController()
        owner = runner(item, controller)
        result = await owner.run(
            replace(spec(), target_module="game_monitor"), fixture or item.fixture
        )
        assert result.status is RunStatus.BLOCKED_UPSTREAM
        assert not controller.started.is_set() and owner.pending_count == 0
