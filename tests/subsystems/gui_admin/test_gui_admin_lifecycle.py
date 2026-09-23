"""通信方式に依存せず、任意GUIの所有タスクと失敗境界を確認する。"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.gui_admin import load_gui_admin_config
from app.config.minimum_brain import load_minimum_brain_config
from app.runtime.kernel.clock import FakeRuntimeClock
from app.subsystems.gui_admin.contracts import GuiAdminAvailability
from app.subsystems.gui_admin.lifecycle import GuiAdminSubsystem


class Transport:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.live = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.fail_start = False
        self.fail_stop = False

    async def start(self) -> None:
        self.starts += 1
        self.entered.set()
        await self.release.wait()
        self.live = True
        if self.fail_start:
            raise RuntimeError("非公開の模擬接続情報")

    async def stop(self) -> None:
        self.stops += 1
        if self.fail_stop:
            raise RuntimeError("非公開の模擬停止情報")
        self.live = False


def subsystem(transport: Transport) -> GuiAdminSubsystem:
    config = load_gui_admin_config(Path("resources/config/v2/gui_admin.yaml").read_text())
    config = replace(
        config,
        gui_http_transport_policy=replace(
            config.gui_http_transport_policy,
            shutdown_grace_seconds=0.05,
        ),
    )
    brain = load_minimum_brain_config(Path("resources/config/v2/minimum_brain.yaml").read_text())
    return GuiAdminSubsystem(
        config,
        brain,
        FakeRuntimeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)),
        lambda configured, application: transport,
    )


@pytest.mark.asyncio
async def test_concurrent_start_and_idempotent_stop_own_one_transport() -> None:
    transport = Transport()
    gui = subsystem(transport)
    states = await asyncio.gather(gui.start(), gui.start())
    assert all(state.availability is GuiAdminAvailability.AVAILABLE for state in states)
    assert transport.starts == 1
    results = await asyncio.gather(gui.stop(), gui.stop())
    assert all(result.completed and result.pending_task_count == 0 for result in results)
    assert transport.stops == 1 and not transport.live
    assert gui.state.availability is GuiAdminAvailability.UNAVAILABLE
    assert (await gui.start()).availability is GuiAdminAvailability.UNAVAILABLE
    assert transport.starts == 1


@pytest.mark.asyncio
async def test_failed_start_closes_partial_resources_without_exposing_exception() -> None:
    transport = Transport()
    transport.fail_start = True
    gui = subsystem(transport)
    state = await gui.start()
    assert state.reason_codes == ("GUI_BIND_FAILED",)
    assert state.availability is GuiAdminAvailability.UNAVAILABLE
    assert not transport.live and transport.stops == 1
    assert gui.pending_task_count == 0
    assert "非公開" not in repr(state)


@pytest.mark.asyncio
async def test_cancelled_start_reaps_startup_and_transport() -> None:
    transport = Transport()
    transport.release.clear()
    gui = subsystem(transport)
    task = asyncio.create_task(gui.start())
    await transport.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gui.pending_task_count == 0
    assert transport.stops == 1 and not transport.live
    assert (await gui.stop()).completed


@pytest.mark.asyncio
async def test_failed_stop_is_not_success_and_can_retry() -> None:
    transport = Transport()
    gui = subsystem(transport)
    await gui.start()
    transport.fail_stop = True
    failed = await gui.stop()
    assert not failed.completed
    assert failed.reason_codes == ("GUI_SHUTDOWN_FAILED",)
    assert "非公開" not in repr(failed)
    transport.fail_stop = False
    assert (await gui.stop()).completed
    assert not transport.live


@pytest.mark.asyncio
async def test_noncooperative_start_reports_timeout_and_late_resources_are_reaped() -> None:
    class DelayedTransport(Transport):
        async def start(self) -> None:
            self.starts += 1
            self.entered.set()
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    continue
            self.live = True

    transport = DelayedTransport()
    transport.release.clear()
    gui = subsystem(transport)
    start = asyncio.create_task(gui.start())
    await transport.entered.wait()
    try:
        result = await gui.stop()
        assert not result.completed and result.pending_task_count > 0
        assert "GUI_SHUTDOWN_TIMED_OUT" in result.reason_codes
        transport.release.set()
        await start
        assert (await gui.stop()).completed
        assert gui.pending_task_count == 0 and not transport.live
    finally:
        transport.release.set()
        await asyncio.gather(start, return_exceptions=True)
        await gui.stop()


@pytest.mark.asyncio
async def test_stop_before_start_acquires_no_transport() -> None:
    transport = Transport()
    gui = subsystem(transport)
    assert (await gui.stop()).completed
    assert (await gui.start()).availability is GuiAdminAvailability.UNAVAILABLE
    assert transport.starts == transport.stops == 0
