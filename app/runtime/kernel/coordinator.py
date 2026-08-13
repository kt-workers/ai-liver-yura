from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.domain.contracts.common import utc_instant

from .cancellation import CancellationRegistry, CancellationToken
from .clock import RuntimeClock
from .contracts import (
    CancellationRecord,
    CoordinatorState,
    LaneDiagnostics,
    LaneErrorPolicy,
    QueueAdmission,
    QueueAdmissionStatus,
    QueuePolicy,
    RuntimeDiagnosticsSnapshot,
    RuntimeHealth,
    RuntimeWorkItem,
    WorkDisposition,
    WorkOutcome,
)
from .queue import BoundedWorkQueue, Coalescer

WorkHandler = Callable[[RuntimeWorkItem[Any], CancellationToken], Awaitable[Any]]
StaleValidator = Callable[[RuntimeWorkItem[Any]], bool]


@dataclass(frozen=True, slots=True)
class RuntimeLanePolicy:
    lane_id: str
    capacity: int
    queue_policy: QueuePolicy
    max_in_flight: int = 1
    max_priority_burst: int = 8
    cancellation_grace_seconds: float = 1.0
    error_policy: LaneErrorPolicy = LaneErrorPolicy.ISOLATE

    def __post_init__(self) -> None:
        if not self.lane_id.strip():
            raise ValueError("lane_id must be non-empty")
        if type(self.max_in_flight) is not int or self.max_in_flight < 1:
            raise ValueError("max_in_flight must be a positive int")
        if (
            type(self.cancellation_grace_seconds) not in (int, float)
            or self.cancellation_grace_seconds < 0
        ):
            raise ValueError("cancellation_grace_seconds must be non-negative")


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
    def __init__(self, clock: RuntimeClock) -> None:
        self._clock = clock
        self._state = CoordinatorState.CREATED
        self._lanes: dict[str, _Lane] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._running_items: dict[str, RuntimeWorkItem[Any]] = {}
        self._cancellations = CancellationRegistry()
        self._outcomes: asyncio.Queue[WorkOutcome[Any]] = asyncio.Queue()
        self._close_hooks: list[Callable[[], Awaitable[None]]] = []
        self._stop_lock = asyncio.Lock()

    @property
    def state(self) -> CoordinatorState:
        return self._state

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
                policy.capacity,
                policy.queue_policy,
                max_priority_burst=policy.max_priority_burst,
                coalescer=coalescer,
            ),
            handler,
            stale_validator or (lambda _: True),
            asyncio.Event(),
        )

    def register_close_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
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
            self._state is CoordinatorState.STOPPING and item.shutdown_control
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
                    token.cancel(
                        self._cancellation_record(work_id, reason)
                    )
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
            if self._state is CoordinatorState.CREATED:
                await self._close_resources()
                self._state = CoordinatorState.STOPPED
                return
            self._state = CoordinatorState.STOPPING
            for lane in self._lanes.values():
                for item in tuple(lane.queue.items()):
                    if not item.shutdown_control:
                        self.cancel(item.work_id, "coordinator shutdown")
                lane.wake.set()
            for work_id in tuple(self._running_tasks):
                self.cancel(work_id, "coordinator shutdown")
            max_grace = max(
                (lane.policy.cancellation_grace_seconds for lane in self._lanes.values()),
                default=0.0,
            )
            await self._await_running_with_grace(max_grace)
            for lane in self._lanes.values():
                lane.wake.set()
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
            await self._close_resources()
            if self._running_tasks or self._tasks:
                raise RuntimeError("runtime shutdown left pending owned tasks")
            self._state = CoordinatorState.STOPPED

    async def _await_running_with_grace(self, grace: float) -> None:
        tasks = tuple(self._running_tasks.values())
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=grace)
        for task in pending:
            task.cancel()
        if pending:
            _, still_pending = await asyncio.wait(pending, timeout=max(grace, 0.05))
            if still_pending:
                raise RuntimeError("runtime tasks ignored cancellation grace")

    async def _close_resources(self) -> None:
        for hook in reversed(self._close_hooks):
            await hook()

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
        return RuntimeDiagnosticsSnapshot(
            self._state, health, len(self._tasks) + len(self._running_tasks), tuple(lanes), now
        )

    async def _worker(self, lane: _Lane) -> None:
        while True:
            if (
                self._state is CoordinatorState.STOPPING
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
            if item.deadline_at is not None and utc_instant(now) >= utc_instant(item.deadline_at):
                disposition = WorkDisposition.TIMED_OUT
            elif not lane.stale_validator(item):
                disposition = WorkDisposition.STALE
            else:
                result = await lane.handler(item, token)
                if token.cancelled:
                    disposition = WorkDisposition.CANCELLED
                elif not lane.stale_validator(item):
                    disposition = WorkDisposition.STALE
                elif item.deadline_at is not None and utc_instant(self._clock.now()) >= utc_instant(
                    item.deadline_at
                ):
                    disposition = WorkDisposition.TIMED_OUT
        except asyncio.CancelledError:
            disposition = WorkDisposition.CANCELLED
        except Exception as exc:
            disposition = WorkDisposition.FAILED
            error = type(exc).__name__
            lane.last_error = error
            if lane.policy.error_policy is LaneErrorPolicy.FAIL_FAST:
                asyncio.create_task(self.stop())
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
