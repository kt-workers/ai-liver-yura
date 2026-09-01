from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.contracts.common import require_identifier, require_revision
from app.runtime.kernel.clock import RuntimeClock
from app.runtime.shutdown import (
    RuntimeShutdownFailure,
    RuntimeShutdownPolicy,
    RuntimeShutdownStage,
)


class DependencyState(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class DependencyRetryPolicy:
    policy_id: str
    policy_revision: int
    dependency_id: str
    retry_enabled: bool
    max_retry_attempts: int
    initial_backoff_seconds: float
    backoff_multiplier: float
    max_backoff_seconds: float
    diagnostic_min_interval_seconds: float

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "dependency retry policy_id")
        require_revision(self.policy_revision, "dependency retry policy_revision")
        require_identifier(self.dependency_id, "dependency_id")
        if type(self.retry_enabled) is not bool:
            raise ValueError("retry_enabledはboolでなければなりません")
        if type(self.max_retry_attempts) is not int or self.max_retry_attempts < 0:
            raise ValueError("max_retry_attemptsは0以上のintでなければなりません")
        self._finite_positive(self.initial_backoff_seconds, "initial_backoff_seconds")
        if (
            type(self.backoff_multiplier) not in (int, float)
            or not isfinite(self.backoff_multiplier)
            or self.backoff_multiplier < 1
        ):
            raise ValueError("backoff_multiplierはfiniteな1以上のnumberでなければなりません")
        self._finite_positive(self.max_backoff_seconds, "max_backoff_seconds")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_secondsはinitial_backoff_seconds以上でなければなりません")
        if (
            type(self.diagnostic_min_interval_seconds) not in (int, float)
            or not isfinite(self.diagnostic_min_interval_seconds)
            or self.diagnostic_min_interval_seconds < 0
        ):
            raise ValueError(
                "diagnostic_min_interval_secondsはfiniteな0以上のnumberでなければなりません"
            )

    @staticmethod
    def _finite_positive(value: object, name: str) -> None:
        if type(value) not in (int, float) or not isfinite(value) or value <= 0:
            raise ValueError(f"{name}はfiniteな正のnumberでなければなりません")

    def delay_for(self, retry_number: int) -> float:
        if type(retry_number) is not int or retry_number < 1:
            raise ValueError("retry_numberは1以上のintでなければなりません")
        return float(
            min(
                self.max_backoff_seconds,
                self.initial_backoff_seconds
                * self.backoff_multiplier ** (retry_number - 1),
            )
        )

    def same_generation(self, other: DependencyRetryPolicy) -> bool:
        return (
            self.policy_id == other.policy_id
            and self.policy_revision == other.policy_revision
        )


@dataclass(frozen=True, slots=True)
class DependencyFailure:
    failure_code: str
    retryable: bool

    def __post_init__(self) -> None:
        require_identifier(self.failure_code, "dependency failure_code")
        if type(self.retryable) is not bool:
            raise ValueError("retryableはboolでなければなりません")


@dataclass(frozen=True, slots=True)
class DependencySnapshot:
    dependency_id: str
    state: DependencyState
    failure_count: int
    retry_attempts: int
    last_failure_code: str | None
    retry_policy_id: str
    retry_policy_revision: int
    close_failed: bool
    updated_at: datetime


Reconnect = Callable[[], Awaitable[DependencyFailure | None]]
Close = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class _Dependency:
    retry_policy: DependencyRetryPolicy
    reconnect: Reconnect
    close: Close
    state: DependencyState
    failure_count: int = 0
    retry_attempts: int = 0
    last_failure_code: str | None = None
    last_failure_retryable: bool = False
    retry_task: asyncio.Task[None] | None = None
    diagnostic_emitted_at: dict[str, datetime] | None = None
    diagnostic_suppressed: dict[str, int] | None = None
    close_failed: bool = False

    def __post_init__(self) -> None:
        if self.diagnostic_emitted_at is None:
            self.diagnostic_emitted_at = {}
        if self.diagnostic_suppressed is None:
            self.diagnostic_suppressed = {}


class RuntimeLifecycle:
    """Optional dependencyのdegraded operationとshutdownを所有する。"""

    def __init__(
        self,
        clock: RuntimeClock,
        shutdown_policy: RuntimeShutdownPolicy,
    ) -> None:
        if not isinstance(shutdown_policy, RuntimeShutdownPolicy):
            raise ValueError("Runtime shutdown policy が必要です")
        self._clock = clock
        self._shutdown_policy = shutdown_policy
        self._dependencies: dict[str, _Dependency] = {}
        self._retired_retry_tasks: set[asyncio.Task[None]] = set()
        self._stopping = False
        self._stop_lock = asyncio.Lock()
        self._shutdown_failures: tuple[RuntimeShutdownFailure, ...] = ()

    @property
    def shutdown_policy(self) -> RuntimeShutdownPolicy:
        return self._shutdown_policy

    @property
    def shutdown_failures(self) -> tuple[RuntimeShutdownFailure, ...]:
        return self._shutdown_failures

    def register_dependency(
        self,
        retry_policy: DependencyRetryPolicy,
        *,
        reconnect: Reconnect,
        close: Close,
    ) -> None:
        if self._stopping:
            raise RuntimeError("shutdown開始後にdependencyは登録できません")
        if not isinstance(retry_policy, DependencyRetryPolicy):
            raise ValueError("Dependency retry policy が必要です")
        dependency_id = retry_policy.dependency_id
        if dependency_id in self._dependencies:
            raise ValueError("dependency_idは重複にできません")
        self._dependencies[dependency_id] = _Dependency(
            retry_policy,
            reconnect,
            close,
            DependencyState.AVAILABLE,
        )

    def update_retry_policy(
        self,
        dependency_id: str,
        policy: DependencyRetryPolicy,
    ) -> DependencySnapshot:
        dependency = self._require(dependency_id)
        if self._stopping:
            raise RuntimeError("shutdown開始後にretry policyは変更できません")
        if not isinstance(policy, DependencyRetryPolicy) or policy.dependency_id != dependency_id:
            raise ValueError("retry policyのdependency_idが一致しません")
        current = dependency.retry_policy
        if current.same_generation(policy):
            if current != policy:
                raise ValueError("同一retry policy generationの内容を変更できません")
            return self.snapshot(dependency_id)
        if (
            policy.policy_id == current.policy_id
            and policy.policy_revision <= current.policy_revision
        ):
            raise ValueError("retry policy revisionを巻き戻せません")
        task = dependency.retry_task
        if task is not None and not task.done():
            task.cancel()
            self._retired_retry_tasks.add(task)
            task.add_done_callback(self._retired_retry_tasks.discard)
        dependency.retry_policy = policy
        dependency.retry_attempts = 0
        dependency.retry_task = None
        return self.snapshot(dependency_id)

    def snapshot(self, dependency_id: str) -> DependencySnapshot:
        dependency = self._require(dependency_id)
        policy = dependency.retry_policy
        return DependencySnapshot(
            dependency_id,
            dependency.state,
            dependency.failure_count,
            dependency.retry_attempts,
            dependency.last_failure_code,
            policy.policy_id,
            policy.policy_revision,
            dependency.close_failed,
            self._clock.now(),
        )

    def report_failure(
        self,
        dependency_id: str,
        failure: DependencyFailure,
    ) -> DependencySnapshot:
        dependency = self._require(dependency_id)
        if not isinstance(failure, DependencyFailure):
            raise ValueError("typed DependencyFailure が必要です")
        if self._stopping:
            return self.snapshot(dependency_id)
        self._apply_failure(dependency, failure)
        return self.snapshot(dependency_id)

    def schedule_reconnect(self, dependency_id: str) -> bool:
        dependency = self._require(dependency_id)
        policy = dependency.retry_policy
        if (
            self._stopping
            or dependency.state is not DependencyState.DEGRADED
            or not policy.retry_enabled
            or dependency.retry_attempts >= policy.max_retry_attempts
        ):
            return False
        if dependency.retry_task is not None and not dependency.retry_task.done():
            return False
        dependency.retry_task = asyncio.create_task(
            self._reconnect(dependency_id, policy),
            name=f"runtime-reconnect:{dependency_id}",
        )
        return True

    def allow_diagnostic(self, dependency_id: str, failure_code: str) -> bool:
        require_identifier(failure_code, "dependency failure_code")
        dependency = self._require(dependency_id)
        assert dependency.diagnostic_emitted_at is not None
        assert dependency.diagnostic_suppressed is not None
        fingerprint = self._diagnostic_fingerprint(dependency_id, failure_code)
        now = self._clock.now()
        previous = dependency.diagnostic_emitted_at.get(fingerprint)
        interval = dependency.retry_policy.diagnostic_min_interval_seconds
        if previous is not None and (now - previous).total_seconds() < interval:
            dependency.diagnostic_suppressed[fingerprint] = (
                dependency.diagnostic_suppressed.get(fingerprint, 0) + 1
            )
            return False
        dependency.diagnostic_emitted_at[fingerprint] = now
        return True

    def suppressed_diagnostic_count(self, dependency_id: str, failure_code: str) -> int:
        dependency = self._require(dependency_id)
        assert dependency.diagnostic_suppressed is not None
        return dependency.diagnostic_suppressed.get(
            self._diagnostic_fingerprint(dependency_id, failure_code),
            0,
        )

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
            failures: list[RuntimeShutdownFailure] = []
            for dependency in reversed(tuple(self._dependencies.values())):
                dependency.state = DependencyState.CLOSING
                try:
                    await asyncio.wait_for(
                        dependency.close(),
                        timeout=self._shutdown_policy.resource_close_grace_seconds,
                    )
                except Exception as error:
                    dependency.close_failed = True
                    dependency.last_failure_code = type(error).__name__
                    failures.append(
                        RuntimeShutdownFailure(
                            RuntimeShutdownStage.RESOURCE_CLOSE,
                            type(error).__name__,
                        )
                    )
                dependency.state = DependencyState.CLOSED
            self._shutdown_failures = tuple(failures)
            return self.snapshots()

    async def close(self) -> None:
        await self.stop()
        if self._shutdown_failures:
            from app.runtime.shutdown import RuntimeShutdownError

            raise RuntimeShutdownError(self._shutdown_failures)

    def snapshots(self) -> tuple[DependencySnapshot, ...]:
        return tuple(self.snapshot(dependency_id) for dependency_id in self._dependencies)

    async def _reconnect(
        self,
        dependency_id: str,
        cycle_policy: DependencyRetryPolicy,
    ) -> None:
        dependency = self._require(dependency_id)
        while (
            not self._stopping
            and dependency.state is DependencyState.DEGRADED
            and self._policy_is_current(dependency, cycle_policy)
            and dependency.retry_attempts < cycle_policy.max_retry_attempts
        ):
            retry_number = dependency.retry_attempts + 1
            await self._clock.sleep(cycle_policy.delay_for(retry_number))
            if self._stopping or not self._policy_is_current(dependency, cycle_policy):
                return
            dependency.retry_attempts = retry_number
            try:
                failure = await dependency.reconnect()
            except asyncio.CancelledError:
                raise
            except Exception:
                failure = DependencyFailure("unclassified_reconnect_failure", False)
            if self._stopping or not self._policy_is_current(dependency, cycle_policy):
                return
            if failure is None:
                dependency.state = DependencyState.AVAILABLE
                dependency.failure_count = 0
                dependency.retry_attempts = 0
                dependency.last_failure_code = None
                dependency.last_failure_retryable = False
                return
            if not isinstance(failure, DependencyFailure):
                failure = DependencyFailure("invalid_reconnect_result", False)
            self._apply_failure(dependency, failure)
        if (
            dependency.state is DependencyState.DEGRADED
            and dependency.retry_attempts >= cycle_policy.max_retry_attempts
        ):
            dependency.state = DependencyState.UNAVAILABLE

    @staticmethod
    def _apply_failure(dependency: _Dependency, failure: DependencyFailure) -> None:
        dependency.failure_count += 1
        dependency.last_failure_code = failure.failure_code
        dependency.last_failure_retryable = failure.retryable
        policy = dependency.retry_policy
        can_retry = (
            failure.retryable
            and policy.retry_enabled
            and dependency.retry_attempts < policy.max_retry_attempts
        )
        dependency.state = DependencyState.DEGRADED if can_retry else DependencyState.UNAVAILABLE

    @staticmethod
    def _policy_is_current(
        dependency: _Dependency,
        cycle_policy: DependencyRetryPolicy,
    ) -> bool:
        return dependency.retry_policy == cycle_policy

    async def _await_retries(self) -> None:
        tasks = {
            dependency.retry_task
            for dependency in self._dependencies.values()
            if dependency.retry_task is not None and not dependency.retry_task.done()
        }
        tasks.update(task for task in self._retired_retry_tasks if not task.done())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _diagnostic_fingerprint(dependency_id: str, failure_code: str) -> str:
        return f"{dependency_id}:{failure_code}"

    def _require(self, dependency_id: str) -> _Dependency:
        try:
            return self._dependencies[dependency_id]
        except KeyError as error:
            raise ValueError("未登録のdependencyです") from error
