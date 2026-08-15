from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.runtime.kernel.clock import RuntimeClock


class DependencyState(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attemptsは1以上のintでなければなりません")
        for value, name in (
            (self.base_delay_seconds, "base_delay_seconds"),
            (self.max_delay_seconds, "max_delay_seconds"),
        ):
            if type(value) not in (int, float) or value < 0:
                raise ValueError(f"{name}は0以上のnumberでなければなりません")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_secondsはbase_delay_seconds以上でなければなりません")

    def delay_for(self, attempt: int) -> float:
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attemptは1以上のintでなければなりません")
        return float(
            min(self.max_delay_seconds, self.base_delay_seconds * 2 ** (attempt - 1))
        )


@dataclass(frozen=True, slots=True)
class DependencySnapshot:
    dependency_id: str
    state: DependencyState
    failure_count: int
    last_error_class: str | None
    updated_at: datetime


Reconnect = Callable[[], Awaitable[None]]
Close = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class _Dependency:
    retry_policy: RetryPolicy
    reconnect: Reconnect
    close: Close
    state: DependencyState
    failure_count: int = 0
    last_error_class: str | None = None
    retry_task: asyncio.Task[None] | None = None
    last_diagnostic_at: datetime | None = None


class RuntimeLifecycle:
    """Optional dependencyのdegraded operationとshutdownを所有する。"""

    def __init__(self, clock: RuntimeClock) -> None:
        self._clock = clock
        self._dependencies: dict[str, _Dependency] = {}
        self._stopping = False
        self._stop_lock = asyncio.Lock()

    def register_dependency(
        self,
        dependency_id: str,
        retry_policy: RetryPolicy,
        *,
        reconnect: Reconnect,
        close: Close,
    ) -> None:
        if self._stopping:
            raise RuntimeError("shutdown開始後にdependencyは登録できません")
        if not dependency_id.strip() or dependency_id in self._dependencies:
            raise ValueError("dependency_idは空または重複にできません")
        self._dependencies[dependency_id] = _Dependency(
            retry_policy, reconnect, close, DependencyState.AVAILABLE
        )

    def snapshot(self, dependency_id: str) -> DependencySnapshot:
        dependency = self._require(dependency_id)
        return DependencySnapshot(
            dependency_id,
            dependency.state,
            dependency.failure_count,
            dependency.last_error_class,
            self._clock.now(),
        )

    def report_failure(self, dependency_id: str, error: Exception) -> DependencySnapshot:
        dependency = self._require(dependency_id)
        if self._stopping:
            return self.snapshot(dependency_id)
        dependency.failure_count += 1
        dependency.last_error_class = type(error).__name__
        dependency.state = (
            DependencyState.UNAVAILABLE
            if dependency.failure_count >= dependency.retry_policy.max_attempts
            else DependencyState.DEGRADED
        )
        return self.snapshot(dependency_id)

    def schedule_reconnect(self, dependency_id: str) -> bool:
        dependency = self._require(dependency_id)
        if self._stopping or dependency.state is not DependencyState.DEGRADED:
            return False
        if dependency.retry_task is not None and not dependency.retry_task.done():
            return False
        dependency.retry_task = asyncio.create_task(
            self._reconnect(dependency_id), name=f"runtime-reconnect:{dependency_id}"
        )
        return True

    def allow_diagnostic(self, dependency_id: str, minimum_interval_seconds: float) -> bool:
        if type(minimum_interval_seconds) not in (int, float) or minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_secondsは0以上のnumberでなければなりません")
        dependency = self._require(dependency_id)
        now = self._clock.now()
        previous = dependency.last_diagnostic_at
        if previous is not None and (now - previous).total_seconds() < minimum_interval_seconds:
            return False
        dependency.last_diagnostic_at = now
        return True

    async def stop(self) -> tuple[DependencySnapshot, ...]:
        async with self._stop_lock:
            if self._stopping:
                await self._await_retries()
                return self.snapshots()
            self._stopping = True
            for dependency in self._dependencies.values():
                task = dependency.retry_task
                if task is not None and not task.done():
                    task.cancel()
            await self._await_retries()
            for dependency in reversed(tuple(self._dependencies.values())):
                dependency.state = DependencyState.CLOSING
                try:
                    await dependency.close()
                except Exception as error:
                    dependency.last_error_class = type(error).__name__
                dependency.state = DependencyState.CLOSED
            return self.snapshots()

    async def close(self) -> None:
        await self.stop()

    def snapshots(self) -> tuple[DependencySnapshot, ...]:
        return tuple(self.snapshot(dependency_id) for dependency_id in self._dependencies)

    async def _reconnect(self, dependency_id: str) -> None:
        dependency = self._require(dependency_id)
        while not self._stopping and dependency.state is DependencyState.DEGRADED:
            await self._clock.sleep(dependency.retry_policy.delay_for(dependency.failure_count))
            if self._stopping:
                return
            try:
                await dependency.reconnect()
            except Exception as error:
                self.report_failure(dependency_id, error)
            else:
                dependency.state = DependencyState.AVAILABLE
                dependency.failure_count = 0
                dependency.last_error_class = None

    async def _await_retries(self) -> None:
        tasks = tuple(
            dependency.retry_task
            for dependency in self._dependencies.values()
            if dependency.retry_task is not None and not dependency.retry_task.done()
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _require(self, dependency_id: str) -> _Dependency:
        try:
            return self._dependencies[dependency_id]
        except KeyError as error:
            raise ValueError("未登録のdependencyです") from error
