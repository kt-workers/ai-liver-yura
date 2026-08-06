from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from app.utils.trace import TraceLogger


class ManagedRuntimeThread(Protocol):
    """Runtimeが開始・停止を管理するWorker Threadの最小契約。"""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def is_alive(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class RuntimeThreadShutdownPolicy:
    """Worker Thread終了待ちの方針。"""

    join_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        timeout = self.join_timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("join_timeout_seconds must be a number")
        normalized = float(timeout)
        if not math.isfinite(normalized) or not 0.1 <= normalized <= 300.0:
            raise ValueError("join_timeout_seconds must be between 0.1 and 300")
        object.__setattr__(self, "join_timeout_seconds", normalized)


@dataclass(frozen=True, slots=True)
class RuntimeWorkerShutdownStatus:
    planner_alive: bool
    executor_alive: bool
    timeout_seconds: float

    @property
    def timed_out(self) -> bool:
        return self.planner_alive or self.executor_alive


class RuntimeWorkerThreads:
    """Planner／Executor ThreadのLifecycleだけを管理する。"""

    def __init__(
        self,
        *,
        planner_thread: ManagedRuntimeThread,
        executor_thread: ManagedRuntimeThread,
        trace_logger: TraceLogger,
        shutdown_policy: RuntimeThreadShutdownPolicy | None = None,
    ) -> None:
        self._planner = planner_thread
        self._executor = executor_thread
        self._trace_logger = trace_logger
        self._shutdown_policy = shutdown_policy or RuntimeThreadShutdownPolicy()

    def start(self, *, enabled: bool) -> None:
        if not enabled:
            self._trace_logger.info(
                "runtime_coordinator:threads:skipped",
                reason="autonomous_planning_disabled",
            )
            return

        for _, worker in self._workers():
            if not worker.is_alive():
                worker.start()

        self._trace_logger.info(
            "runtime_coordinator:threads:start",
            activity_planner_thread_alive=self._planner.is_alive(),
            activity_executor_thread_alive=self._executor.is_alive(),
        )

    def stop(self, *, enabled: bool) -> RuntimeWorkerShutdownStatus:
        timeout = self._shutdown_policy.join_timeout_seconds
        if not enabled:
            return RuntimeWorkerShutdownStatus(
                planner_alive=self._planner.is_alive(),
                executor_alive=self._executor.is_alive(),
                timeout_seconds=timeout,
            )

        for _, worker in self._workers():
            worker.stop()
        for _, worker in self._workers():
            if worker.is_alive():
                worker.join(timeout=timeout)

        status = RuntimeWorkerShutdownStatus(
            planner_alive=self._planner.is_alive(),
            executor_alive=self._executor.is_alive(),
            timeout_seconds=timeout,
        )
        if status.timed_out:
            self._trace_logger.warning(
                "runtime_coordinator:threads:shutdown_timeout",
                timeout_seconds=status.timeout_seconds,
                activity_planner_thread_alive=status.planner_alive,
                activity_executor_thread_alive=status.executor_alive,
            )
        self._trace_logger.info(
            "runtime_coordinator:threads:stopped",
            activity_planner_thread_alive=status.planner_alive,
            activity_executor_thread_alive=status.executor_alive,
        )
        return status

    def _workers(
        self,
    ) -> tuple[
        tuple[str, ManagedRuntimeThread],
        tuple[str, ManagedRuntimeThread],
    ]:
        return (
            ("activity_planner_thread", self._planner),
            ("activity_executor_thread", self._executor),
        )
