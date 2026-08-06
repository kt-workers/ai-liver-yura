from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.plugins import PluginManager
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_planner_thread import ActivityPlannerThread
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.runtime_loop import RuntimeLoop
from app.runtime.runtime_worker_threads import (
    RuntimeThreadShutdownPolicy,
    RuntimeWorkerThreads,
)
from app.utils.trace import TraceLogger


class RuntimeHostController:
    """Runtime初期化、実行Loop、停止時cleanupの順序を所有する。"""

    def __init__(
        self,
        *,
        runtime_loop: RuntimeLoop,
        activity_planner_thread: ActivityPlannerThread,
        activity_executor_thread: ActivityExecutorThread,
        plugin_manager: PluginManager | None,
        ongoing_activity_coordinator: OngoingActivityCoordinator,
        async_initializers: tuple[Callable[[], Awaitable[None]], ...],
        trace_logger: TraceLogger,
        idle_sleep_seconds: float = 0.05,
        thread_join_timeout_seconds: float = 30.0,
    ) -> None:
        self._runtime_loop = runtime_loop
        self._plugin_manager = plugin_manager
        self._ongoing = ongoing_activity_coordinator
        self._async_initializers = async_initializers
        self._trace_logger = trace_logger
        self._idle_sleep_seconds = idle_sleep_seconds
        self._worker_threads = RuntimeWorkerThreads(
            planner_thread=activity_planner_thread,
            executor_thread=activity_executor_thread,
            trace_logger=trace_logger,
            shutdown_policy=RuntimeThreadShutdownPolicy(
                join_timeout_seconds=thread_join_timeout_seconds,
            ),
        )
        self._initializers_completed = False
        self._running = False

    async def run(self) -> None:
        self._running = True
        self._trace_logger.info("runtime_coordinator:run:start")
        await self._run_async_initializers()
        self._worker_threads.start(
            enabled=self._runtime_loop.autonomous_planning_enabled,
        )
        while self._running:
            action_plan_group = await self._runtime_loop.run_once()
            if action_plan_group is None:
                self._trace_logger.write("runtime_coordinator:run:idle_sleep")
                await asyncio.sleep(self._idle_sleep_seconds)

    def stop(self) -> None:
        self._trace_logger.info("runtime_coordinator:stop")
        self._running = False
        self._worker_threads.stop(
            enabled=self._runtime_loop.autonomous_planning_enabled,
        )
        if self._plugin_manager is not None:
            self._plugin_manager.shutdown_plugins()
        self._ongoing.cancel(reason="runtime_stopped")

    async def _run_async_initializers(self) -> None:
        if self._initializers_completed:
            return
        for initializer in self._async_initializers:
            try:
                await initializer()
            except Exception as error:
                self._trace_logger.error(
                    "runtime_coordinator:async_initializer_failed",
                    initializer=getattr(
                        initializer,
                        "__qualname__",
                        type(initializer).__name__,
                    ),
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
        self._initializers_completed = True
