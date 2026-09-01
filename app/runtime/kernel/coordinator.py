from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.domain.contracts.common import utc_instant
from app.runtime.shutdown import (
    RuntimeShutdownError,
    RuntimeShutdownFailure,
    RuntimeShutdownPolicy,
    RuntimeShutdownStage,
)

from .cancellation import CancellationRegistry, CancellationToken
from .clock import RuntimeClock
from .contracts import (
    CancellationRecord,
    CoordinatorState,
    LaneDiagnostics,
    LaneErrorPolicy,
    QueueAdmission,
    QueueAdmissionStatus,
    RuntimeDiagnosticsSnapshot,
    RuntimeHealth,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkDisposition,
    WorkOutcome,
)
from .queue import BoundedWorkQueue, Coalescer

WorkHandler = Callable[[RuntimeWorkItem[Any], CancellationToken], Awaitable[Any]]
StaleValidator = Callable[[RuntimeWorkItem[Any]], bool]
ShutdownHook = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class _Lane:
    policy: RuntimeLanePolicy
    queue: BoundedWorkQueue[Any]
    handler: WorkHandler
    stale_validator: StaleValidator
    wake: asyncio.Event
    in_flight: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    stale: int = 0
    rejected: int = 0
    last_error: str | None = None


class RuntimeCoordinator:
    def __init__(
        self,
        clock: RuntimeClock,
        scheduler_policy: RuntimeSchedulerPolicy,
        shutdown_policy: RuntimeShutdownPolicy,
    ) -> None:
        if not isinstance(shutdown_policy, RuntimeShutdownPolicy):
            raise ValueError("Runtime shutdown policy が必要です")
        self._clock = clock
        self._scheduler_policy = scheduler_policy
        self._shutdown_policy = shutdown_policy
        self._state = CoordinatorState.CREATED
        self._lanes: dict[str, _Lane] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._running_items: dict[str, RuntimeWorkItem[Any]] = {}
        self._cancellations = CancellationRegistry()
        self._outcomes: asyncio.Queue[WorkOutcome[Any]] = asyncio.Queue()
        self._final_persistence_hooks: list[ShutdownHook] = []
        self._close_hooks: list[ShutdownHook] = []
        self._stop_lock = asyncio.Lock()
        self._shutdown_control_open = False
        self._shutdown_task: asyncio.Task[None] | None = None
        self._shutdown_failures: tuple[RuntimeShutdownFailure, ...] = ()

    @property
    def state(self) -> CoordinatorState:
        return self._state

    @property
    def scheduler_policy(self) -> RuntimeSchedulerPolicy:
        return self._scheduler_policy

    @property
    def shutdown_policy(self) -> RuntimeShutdownPolicy:
        return self._shutdown_policy

    @property
    def shutdown_failures(self) -> tuple[RuntimeShutdownFailure, ...]:
        return self._shutdown_failures

    def register_lane(
        self,
        policy: RuntimeLanePolicy,
        handler: WorkHandler,
        *,
        stale_validator: StaleValidator | None = None,
        coalescer: Coalescer[Any] | None = None,
    ) -> None:
        if self._state is not CoordinatorState.CREATED:
            raise RuntimeError("lanes can only be registered before start")
        if policy.lane_id in self._lanes:
            raise ValueError(f"duplicate lane: {policy.lane_id}")
        self._lanes[policy.lane_id] = _Lane(
            policy,
            BoundedWorkQueue(
                policy.queue_capacity,
                policy.queue_policy,
                max_priority_burst=self._scheduler_policy.max_priority_burst,
                coalescer=coalescer,
            ),
            handler,
            stale_validator or (lambda _: True),
            asyncio.Event(),
        )

    def register_final_persistence_hook(self, hook: ShutdownHook) -> None:
        if self._state is not CoordinatorState.CREATED:
            raise RuntimeError("final persistence hooks can only be registered before start")
        self._final_persistence_hooks.append(hook)

    def register_close_hook(self, hook: ShutdownHook) -> None:
        if self._state is not CoordinatorState.CREATED:
            raise RuntimeError("close hooks can only be registered before start")
        self._close_hooks.append(hook)

    async def start(self) -> None:
        if self._state is not CoordinatorState.CREATED:
            raise RuntimeError("coordinator can only be started once")
        self._state = CoordinatorState.RUNNING
        for lane in self._lanes.values():
            task = asyncio.create_task(
                self._worker(lane), name=f"runtime-lane:{lane.policy.lane_id}"
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def submit(self, item: RuntimeWorkItem[Any]) -> QueueAdmission:
        lane = self._lanes.get(item.lane_id)
        accepts = self._state is CoordinatorState.RUNNING or (
            self._state is CoordinatorState.STOPPING
            and self._shutdown_control_open
            and item.shutdown_control
        )
        if not accepts or lane is None:
            if lane is not None:
                lane.rejected += 1
            return QueueAdmission(QueueAdmissionStatus.REJECTED, None)
        if self._cancellations.is_known(item.work_id):
            lane.rejected += 1
            return QueueAdmission(QueueAdmissionStatus.REJECTED, None)
        self._cancellations.register(item.work_id)
        try:
            admission = lane.queue.put(item)
        except Exception:
            self._cancellations.release(item.work_id)
            raise
        if admission.accepted:
            assert admission.admitted_work_id is not None
            if admission.admitted_work_id != item.work_id:
                raise RuntimeError("queue admitted an unexpected work identity")
            for displaced in admission.displaced_work_ids:
                if displaced != admission.admitted_work_id:
                    self._cancellations.complete(displaced)
            lane.wake.set()
        else:
            self._cancellations.release(item.work_id)
            lane.rejected += 1
        return admission

    def cancel(self, work_id: str, reason: str) -> bool:
        for lane in self._lanes.values():
            removed = lane.queue.remove_work(work_id)
            if removed is not None:
                token = self._cancellations.token_for(work_id)
                if token is not None:
                    token.cancel(self._cancellation_record(work_id, reason))
                self._cancellations.complete(work_id)
                lane.cancelled += 1
                self._outcomes.put_nowait(
                    WorkOutcome(
                        work_id,
                        removed.lane_id,
                        WorkDisposition.CANCELLED,
                        self._clock.now(),
                    )
                )
                return True
        cancelled = self._cancellations.cancel(work_id, reason, self._clock.now())
        task = self._running_tasks.get(work_id)
        running_item = self._running_items.get(work_id)
        if (
            cancelled
            and task is not None
            and running_item is not None
            and running_item.interruptible
        ):
            task.cancel()
        return cancelled

    def _cancellation_record(self, work_id: str, reason: str) -> CancellationRecord:
        return CancellationRecord(work_id, reason, self._clock.now())

    async def next_outcome(self) -> WorkOutcome[Any]:
        return await self._outcomes.get()

    async def stop(self) -> None:
        async with self._stop_lock:
            if self._state is CoordinatorState.STOPPED:
                return
            failures: list[RuntimeShutdownFailure] = list(self._shutdown_failures)
            self._state = CoordinatorState.STOPPING
            self._shutdown_control_open = True
            for lane in self._lanes.values():
                for item in tuple(lane.queue.items()):
                    if not item.shutdown_control:
                        self.cancel(item.work_id, "coordinator shutdown")
                lane.wake.set()
            for work_id in tuple(self._running_tasks):
                self.cancel(work_id, "coordinator shutdown")
            await asyncio.sleep(0)
            self._shutdown_control_open = False
            for lane in self._lanes.values():
                lane.wake.set()

            if not await self._settle_running_tasks(
                self._shutdown_policy.in_flight_settle_grace_seconds
            ):
                failures.append(
                    RuntimeShutdownFailure(
                        RuntimeShutdownStage.IN_FLIGHT_SETTLE,
                        "TimeoutError",
                    )
                )
            for lane in self._lanes.values():
                lane.wake.set()

            failures.extend(await self._run_final_persistence_hooks())
            failures.extend(await self._close_resources())

            if not await self._join_owned_tasks(
                self._shutdown_policy.owned_task_join_grace_seconds
            ):
                failures.append(
                    RuntimeShutdownFailure(
                        RuntimeShutdownStage.OWNED_TASK_JOIN,
                        "TimeoutError",
                    )
                )

            pending_owned = (
                bool(self._running_tasks)
                or bool(self._tasks)
                or any(len(lane.queue) or lane.in_flight for lane in self._lanes.values())
                or bool(self._cancellations.active_work_ids())
            )
            if pending_owned:
                failures.append(
                    RuntimeShutdownFailure(
                        RuntimeShutdownStage.PENDING_OWNED_WORK,
                        "PendingOwnedWork",
                    )
                )
            self._shutdown_failures = self._deduplicate_failures(tuple(failures))
            if pending_owned:
                raise RuntimeShutdownError(self._shutdown_failures)
            self._state = CoordinatorState.STOPPED

    def request_stop(self) -> asyncio.Task[None]:
        task = self._shutdown_task
        if task is None or task.done():
            task = asyncio.create_task(self.stop(), name="runtime-coordinator:stop")
            self._shutdown_task = task
        return task

    async def wait_stopped(self) -> None:
        task = self._shutdown_task
        if task is not None:
            await task
        elif self._state is not CoordinatorState.STOPPED:
            await self.stop()

    async def _settle_running_tasks(self, grace: float) -> bool:
        tasks = tuple(self._running_tasks.values())
        if not tasks:
            return True
        _, pending = await asyncio.wait(tasks, timeout=grace)
        if not pending:
            return True
        for task in pending:
            task.cancel()
        await asyncio.sleep(0)
        return False

    async def _run_final_persistence_hooks(self) -> tuple[RuntimeShutdownFailure, ...]:
        return await self._run_phase_hooks(
            tuple(self._final_persistence_hooks),
            self._shutdown_policy.final_persistence_grace_seconds,
            RuntimeShutdownStage.FINAL_PERSISTENCE,
            reverse=False,
            phase_bounded=True,
        )

    async def _close_resources(self) -> tuple[RuntimeShutdownFailure, ...]:
        return await self._run_phase_hooks(
            tuple(self._close_hooks),
            self._shutdown_policy.resource_close_grace_seconds,
            RuntimeShutdownStage.RESOURCE_CLOSE,
            reverse=True,
            phase_bounded=False,
        )

    @staticmethod
    async def _run_phase_hooks(
        hooks: tuple[ShutdownHook, ...],
        grace_seconds: float,
        stage: RuntimeShutdownStage,
        *,
        reverse: bool,
        phase_bounded: bool,
    ) -> tuple[RuntimeShutdownFailure, ...]:
        ordered = tuple(reversed(hooks)) if reverse else hooks
        failures: list[RuntimeShutdownFailure] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace_seconds
        for hook in ordered:
            timeout = grace_seconds
            if phase_bounded:
                timeout = max(0.0, deadline - loop.time())
            try:
                await asyncio.wait_for(hook(), timeout=timeout)
            except Exception as error:
                failures.append(RuntimeShutdownFailure(stage, type(error).__name__))
        return tuple(failures)

    async def _join_owned_tasks(self, grace: float) -> bool:
        tasks = tuple(self._tasks)
        if not tasks:
            return True
        _, pending = await asyncio.wait(tasks, timeout=grace)
        if not pending:
            return True
        for task in pending:
            task.cancel()
        await asyncio.sleep(0)
        return False

    @staticmethod
    def _deduplicate_failures(
        failures: tuple[RuntimeShutdownFailure, ...],
    ) -> tuple[RuntimeShutdownFailure, ...]:
        seen: set[tuple[RuntimeShutdownStage, str]] = set()
        result: list[RuntimeShutdownFailure] = []
        for failure in failures:
            key = (failure.stage, failure.error_class)
            if key not in seen:
                seen.add(key)
                result.append(failure)
        return tuple(result)

    def diagnostics(self) -> RuntimeDiagnosticsSnapshot:
        now = self._clock.now()
        lanes = []
        for lane_id, lane in self._lanes.items():
            items = lane.queue.items()
            oldest_age = None
            if items:
                oldest = min(utc_instant(item.created_at) for item in items)
                oldest_age = max(0.0, (utc_instant(now) - oldest).total_seconds())
            lanes.append(
                LaneDiagnostics(
                    lane_id,
                    len(lane.queue),
                    lane.in_flight,
                    lane.completed,
                    lane.failed,
                    lane.cancelled,
                    lane.stale,
                    lane.rejected,
                    lane.queue.counts_by_priority(),
                    oldest_age,
                    lane.last_error,
                )
            )
        health = {
            CoordinatorState.RUNNING: RuntimeHealth.HEALTHY,
            CoordinatorState.STOPPING: RuntimeHealth.STOPPING,
            CoordinatorState.STOPPED: RuntimeHealth.STOPPED,
            CoordinatorState.CREATED: RuntimeHealth.STOPPED,
        }[self._state]
        if self._state is CoordinatorState.RUNNING and any(
            lane.last_error for lane in self._lanes.values()
        ):
            health = RuntimeHealth.DEGRADED
        shutdown_owned = int(
            self._shutdown_task is not None and not self._shutdown_task.done()
        )
        return RuntimeDiagnosticsSnapshot(
            self._state,
            health,
            len(self._tasks) + len(self._running_tasks) + shutdown_owned,
            tuple(lanes),
            now,
        )

    async def _worker(self, lane: _Lane) -> None:
        while True:
            if (
                self._state is CoordinatorState.STOPPING
                and not self._shutdown_control_open
                and not len(lane.queue)
                and not lane.in_flight
            ):
                return
            while lane.in_flight < lane.policy.max_in_flight:
                item = lane.queue.get()
                if item is None:
                    break
                token = self._cancellations.token_for(item.work_id)
                if token is None:
                    continue
                task = asyncio.create_task(self._execute(lane, item, token))
                lane.in_flight += 1
                self._running_tasks[item.work_id] = task
                self._running_items[item.work_id] = item
                task.add_done_callback(self._wake_lane(lane))
            lane.wake.clear()
            if (
                self._state is CoordinatorState.STOPPING
                and not self._shutdown_control_open
                and not lane.in_flight
                and not len(lane.queue)
            ):
                return
            await lane.wake.wait()

    @staticmethod
    def _wake_lane(lane: _Lane) -> Callable[[asyncio.Task[None]], None]:
        def wake(_task: asyncio.Task[None]) -> None:
            lane.wake.set()

        return wake

    async def _execute(
        self, lane: _Lane, item: RuntimeWorkItem[Any], token: CancellationToken
    ) -> None:
        disposition = WorkDisposition.COMPLETED
        result: Any = None
        error: str | None = None
        try:
            now = self._clock.now()
            if (
                item.deadline_at is not None
                and utc_instant(now) >= utc_instant(item.deadline_at)
            ):
                disposition = WorkDisposition.TIMED_OUT
            elif not lane.stale_validator(item):
                disposition = WorkDisposition.STALE
            else:
                result = await lane.handler(item, token)
                if token.cancelled:
                    disposition = WorkDisposition.CANCELLED
                elif not lane.stale_validator(item):
                    disposition = WorkDisposition.STALE
                elif (
                    item.deadline_at is not None
                    and utc_instant(self._clock.now())
                    >= utc_instant(item.deadline_at)
                ):
                    disposition = WorkDisposition.TIMED_OUT
        except asyncio.CancelledError:
            disposition = WorkDisposition.CANCELLED
        except Exception as exc:
            disposition = WorkDisposition.FAILED
            error = type(exc).__name__
            lane.last_error = error
            if lane.policy.error_isolation is LaneErrorPolicy.FAIL_FAST_CONTROLLED:
                self.request_stop()
        finally:
            lane.in_flight -= 1
            self._running_tasks.pop(item.work_id, None)
            self._running_items.pop(item.work_id, None)
            self._cancellations.complete(item.work_id)
            if disposition is WorkDisposition.COMPLETED:
                lane.completed += 1
            elif disposition is WorkDisposition.FAILED:
                lane.failed += 1
            elif disposition is WorkDisposition.CANCELLED:
                lane.cancelled += 1
            elif disposition is WorkDisposition.STALE:
                lane.stale += 1
            self._outcomes.put_nowait(
                WorkOutcome(
                    item.work_id,
                    item.lane_id,
                    disposition,
                    self._clock.now(),
                    result,
                    error,
                )
            )
            lane.wake.set()
