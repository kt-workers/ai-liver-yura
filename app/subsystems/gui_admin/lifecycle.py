"""任意GUIの起動・停止と通信資源の回収だけを所有する。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.config.gui_admin import GuiAdminProductionConfig
from app.config.minimum_brain import MinimumBrainProductionConfig
from app.runtime.kernel.clock import RuntimeClock

from .configuration_projection import MinimumBrainConfigurationReadModelProjector
from .contracts import GuiAdminAvailability
from .http_application import GuiHttpApplication


class GuiAdminTransport(Protocol):
    """構築は資源を取得せず、start/stopが待受と接続を所有する。"""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


GuiAdminTransportFactory = Callable[
    [GuiAdminProductionConfig, GuiHttpApplication], GuiAdminTransport
]


@dataclass(frozen=True, slots=True)
class GuiAdminLifecycleState:
    availability: GuiAdminAvailability
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuiAdminStopResult:
    completed: bool
    pending_task_count: int
    reason_codes: tuple[str, ...]


class GuiAdminSubsystem:
    """Coreを停止せず、同時要求にも一つの起動・停止作業を共有する。"""

    def __init__(
        self,
        config: GuiAdminProductionConfig,
        brain_config: MinimumBrainProductionConfig,
        clock: RuntimeClock,
        transport_factory: GuiAdminTransportFactory,
    ) -> None:
        if not isinstance(config, GuiAdminProductionConfig) or not callable(transport_factory):
            raise ValueError("GUIの明示構成と通信factoryが必要です")
        self._config = config
        self._brain_config = brain_config
        self._clock = clock
        self._factory = transport_factory
        self._transport: GuiAdminTransport | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[GuiAdminStopResult] | None = None
        self._transport_stop: asyncio.Task[None] | None = None
        self._closing = False
        self._state = GuiAdminLifecycleState(GuiAdminAvailability.UNAVAILABLE)

    @property
    def state(self) -> GuiAdminLifecycleState:
        return self._state

    @property
    def pending_task_count(self) -> int:
        return sum(
            task is not None and not task.done()
            for task in (self._start_task, self._transport_stop)
        )

    async def start(self) -> GuiAdminLifecycleState:
        if self._closing:
            return self._state
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start())
        try:
            await asyncio.shield(self._start_task)
        except asyncio.CancelledError:
            if asyncio.current_task() is not None and not self._closing:
                await self.stop()
            raise
        if self._state.reason_codes:
            await self.stop()
        return self._state

    async def _start(self) -> None:
        try:
            projection = MinimumBrainConfigurationReadModelProjector(
                self._brain_config, self._clock, self._config.gui_operational_policy
            )
            self._transport = self._factory(self._config, GuiHttpApplication(projection))
            await self._transport.start()
            if not self._closing:
                self._state = GuiAdminLifecycleState(GuiAdminAvailability.AVAILABLE)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._state = GuiAdminLifecycleState(
                GuiAdminAvailability.UNAVAILABLE, ("GUI_BIND_FAILED",)
            )

    async def stop(self) -> GuiAdminStopResult:
        if self._stop_task is None or (
            self._stop_task.done() and not self._stop_task.result().completed
        ):
            if self._transport_stop is not None and self._transport_stop.done():
                self._transport_stop = None
            self._closing = True
            self._stop_task = asyncio.create_task(self._stop())
        return await asyncio.shield(self._stop_task)

    async def _stop(self) -> GuiAdminStopResult:
        deadline = asyncio.get_running_loop().time() + (
            self._config.gui_http_transport_policy.shutdown_grace_seconds
        )
        self._state = GuiAdminLifecycleState(
            GuiAdminAvailability.UNAVAILABLE, self._state.reason_codes
        )
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
        if self._start_task is not None:
            await asyncio.wait(
                {self._start_task}, timeout=max(0.0, deadline - asyncio.get_running_loop().time())
            )
        if self._transport is not None and (
            self._transport_stop is None or self._transport_stop.cancelled()
        ):
            self._transport_stop = asyncio.create_task(self._transport.stop())
        if self._transport_stop is not None:
            await asyncio.wait(
                {self._transport_stop},
                timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
            )
        reasons: list[str] = []
        if self.pending_task_count:
            reasons.append("GUI_SHUTDOWN_TIMED_OUT")
            if self._transport_stop is not None and not self._transport_stop.done():
                self._transport_stop.cancel()
        elif self._transport_stop is not None:
            if self._transport_stop.cancelled() or self._transport_stop.exception() is not None:
                reasons.append("GUI_SHUTDOWN_FAILED")
        if reasons:
            self._state = GuiAdminLifecycleState(
                GuiAdminAvailability.UNAVAILABLE,
                tuple(dict.fromkeys((*self._state.reason_codes, *reasons))),
            )
        return GuiAdminStopResult(not reasons, self.pending_task_count, tuple(reasons))
