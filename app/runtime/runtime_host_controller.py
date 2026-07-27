from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.plugins import PluginManager
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_planner_thread import ActivityPlannerThread
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.runtime_loop import RuntimeLoop
from app.utils.trace import TraceLogger


class RuntimeHostController:
    """Runtime初期化、常駐Thread、停止時cleanupを所有する。"""

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
        thread_join_timeout_seconds: float = 1.0,
    ) -> None:
        self._runtime_loop = runtime_loop
        self._planner_thread = activity_planner_thread
        self._executor_thread = activity_executor_thread
        self._plugin_manager = plugin_manager
        self._ongoing = ongoing_activity_coordinator
        self._async_initializers = async_initializers
        self._trace_logger = trace_logger
        self._idle_sleep_seconds = idle_sleep_seconds
        self._thread_join_timeout_seconds = thread_join_timeout_seconds
        self._initializers_completed = False
        self._running = False

    async def run(self) -> None:
        self._running = True
        self._trace_logger.info("runtime_coordinator:run:start")
        await self._run_async_initializers()
        self._start_threads()
        while self._running:
            action_plan_group = await self._runtime_loop.run_once()
            if action_plan_group is None:
                self._trace_logger.write("runtime_coordinator:run:idle_sleep")
                await asyncio.sleep(self._idle_sleep_seconds)

    def stop(self) -> None:
        self._trace_logger.info("runtime_coordinator:stop")
        self._running = False
        self._stop_threads()
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

    def _start_threads(self) -> None:
        if not self._runtime_loop.autonomous_planning_enabled:
            self._trace_logger.info(
                "runtime_coordinator:threads:skipped",
                reason="autonomous_planning_disabled",
            )
            return
        if not self._planner_thread.is_alive():
            self._planner_thread.start()
        if not self._executor_thread.is_alive():
            self._executor_thread.start()
        self._trace_logger.info(
            "runtime_coordinator:threads:start",
            activity_planner_thread_alive=self._planner_thread.is_alive(),
            activity_executor_thread_alive=self._executor_thread.is_alive(),
        )

    def _stop_threads(self) -> None:
        if not self._runtime_loop.autonomous_planning_enabled:
            return
        self._planner_thread.stop()
        self._executor_thread.stop()
        if self._planner_thread.is_alive():
            self._planner_thread.join(timeout=self._thread_join_timeout_seconds)
        if self._executor_thread.is_alive():
            self._executor_thread.join(timeout=self._thread_join_timeout_seconds)
        self._trace_logger.info(
            "runtime_coordinator:threads:stopped",
            activity_planner_thread_alive=self._planner_thread.is_alive(),
            activity_executor_thread_alive=self._executor_thread.is_alive(),
        )
