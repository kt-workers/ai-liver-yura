from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Generic, TypeVar

from .contracts import (
    QueueAdmission,
    QueueAdmissionStatus,
    QueuePolicy,
    RuntimeWorkItem,
    WorkPriority,
)

T = TypeVar("T")
Coalescer = Callable[[RuntimeWorkItem[T], RuntimeWorkItem[T]], RuntimeWorkItem[T]]


class BoundedWorkQueue(Generic[T]):
    def __init__(
        self,
        capacity: int,
        policy: QueuePolicy,
        *,
        max_priority_burst: int = 8,
        coalescer: Coalescer[T] | None = None,
    ) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be a positive int")
        if type(max_priority_burst) is not int or max_priority_burst < 1:
            raise ValueError("max_priority_burst must be a positive int")
        if policy is QueuePolicy.COALESCE and coalescer is None:
            raise ValueError("coalesce policy requires a coalescer")
        self.capacity = capacity
        self.policy = policy
        self.max_priority_burst = max_priority_burst
        self._coalescer = coalescer
        self._queues: dict[WorkPriority, deque[RuntimeWorkItem[T]]] = {
            priority: deque() for priority in WorkPriority
        }
        self._size = 0
        self._last_priority: WorkPriority | None = None
        self._priority_burst = 0

    def __len__(self) -> int:
        return self._size

    def items(self) -> tuple[RuntimeWorkItem[T], ...]:
        return tuple(item for priority in WorkPriority for item in self._queues[priority])

    def counts_by_priority(self) -> tuple[tuple[WorkPriority, int], ...]:
        return tuple((priority, len(self._queues[priority])) for priority in WorkPriority)

    def put(self, item: RuntimeWorkItem[T]) -> QueueAdmission:
        if any(existing.work_id == item.work_id for existing in self.items()):
            return QueueAdmission(QueueAdmissionStatus.REJECTED, None)
        existing = self._find_by_key(item.queue_key) if item.queue_key is not None else None
        if self.policy is QueuePolicy.LATEST_WINS:
            if item.queue_key is None:
                return QueueAdmission(QueueAdmissionStatus.REJECTED, None)
            if existing is not None:
                displaced = self._remove(existing)
                self._append(item)
                return QueueAdmission(
                    QueueAdmissionStatus.REPLACED, item.work_id, (displaced.work_id,)
                )
        elif self.policy is QueuePolicy.COALESCE and existing is not None:
            assert self._coalescer is not None
            combined = self._coalescer(existing, item)
            if combined.queue_key != item.queue_key:
                raise ValueError("coalescer must preserve queue_key")
            if combined.work_id != item.work_id:
                raise ValueError("coalescer must preserve new work_id")
            if combined.lane_id != item.lane_id:
                raise ValueError("coalescer must preserve lane_id")
            displaced = self._remove(existing)
            self._append(combined)
            return QueueAdmission(
                QueueAdmissionStatus.COALESCED,
                combined.work_id,
                (displaced.work_id, item.work_id),
            )
        elif self.policy is QueuePolicy.REPLACE_SAME_KEY and existing is not None:
            displaced = self._remove(existing)
            self._append(item)
            return QueueAdmission(
                QueueAdmissionStatus.REPLACED, item.work_id, (displaced.work_id,)
            )

        if self._size < self.capacity:
            self._append(item)
            return QueueAdmission(QueueAdmissionStatus.ACCEPTED, item.work_id)

        if self.policy is QueuePolicy.DROP_OLDEST:
            displaced = self._remove_oldest()
            self._append(item)
            return QueueAdmission(
                QueueAdmissionStatus.DROPPED_OLDEST,
                item.work_id,
                (displaced.work_id,),
            )
        return QueueAdmission(QueueAdmissionStatus.REJECTED, None)

    def get(self) -> RuntimeWorkItem[T] | None:
        available = [priority for priority in WorkPriority if self._queues[priority]]
        if not available:
            return None
        selected = available[0]
        if (
            self._last_priority is selected
            and self._priority_burst >= self.max_priority_burst
            and len(available) > 1
            and selected is not WorkPriority.CRITICAL
        ):
            selected = min(
                available[1:],
                key=lambda priority: self._queues[priority][0].created_at.timestamp(),
            )
        item = self._queues[selected].popleft()
        self._size -= 1
        if selected is self._last_priority:
            self._priority_burst += 1
        else:
            self._last_priority = selected
            self._priority_burst = 1
        return item

    def drain(self) -> tuple[RuntimeWorkItem[T], ...]:
        drained = self.items()
        for queue in self._queues.values():
            queue.clear()
        self._size = 0
        return drained

    def remove_work(self, work_id: str) -> RuntimeWorkItem[T] | None:
        for item in self.items():
            if item.work_id == work_id:
                return self._remove(item)
        return None

    def _append(self, item: RuntimeWorkItem[T]) -> None:
        self._queues[item.priority].append(item)
        self._size += 1

    def _find_by_key(self, key: str | None) -> RuntimeWorkItem[T] | None:
        if key is None:
            return None
        return next((item for item in self.items() if item.queue_key == key), None)

    def _remove(self, item: RuntimeWorkItem[T]) -> RuntimeWorkItem[T]:
        self._queues[item.priority].remove(item)
        self._size -= 1
        return item

    def _remove_oldest(self) -> RuntimeWorkItem[T]:
        oldest_item = min(self.items(), key=lambda item: item.created_at.timestamp())
        return self._remove(oldest_item)
