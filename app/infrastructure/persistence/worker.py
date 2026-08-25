"""#359のbounded latest-state snapshot persistence worker。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.runtime.lifecycle import RetryPolicy

from .contracts import (
    DurabilityReceipt,
    DurabilityStatus,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceSnapshotEnvelope,
)
from .snapshots import LifecycleSnapshotRepositoryPort


@dataclass(frozen=True, slots=True)
class SnapshotPersistenceRequest:
    request_id: str
    envelope: PersistenceSnapshotEnvelope
    latest_state_coalescible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_idが不正です")
        if not isinstance(self.envelope, PersistenceSnapshotEnvelope):
            raise ValueError("envelopeが不正です")
        if type(self.latest_state_coalescible) is not bool:
            raise ValueError("latest_state_coalescibleが不正です")


class SnapshotPersistenceWorker:
    """owner意味を解釈せず、bounded queue内だけでlatest snapshotをcoalesceする。"""

    def __init__(
        self,
        repository: LifecycleSnapshotRepositoryPort,
        *,
        max_pending: int = 32,
        retry_policy: RetryPolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if type(max_pending) is not int or not 1 <= max_pending <= 256:
            raise ValueError("max_pendingが不正です")
        self._repository = repository
        self._max_pending = max_pending
        self._retry_policy = retry_policy or RetryPolicy(3, 0.01, 0.1)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._queued: dict[
            tuple[str, str], tuple[SnapshotPersistenceRequest, asyncio.Future[DurabilityReceipt]]
        ] = {}
        self._closed = False

    def submit(self, request: SnapshotPersistenceRequest) -> asyncio.Future[DurabilityReceipt]:
        if self._closed:
            return self._immediate(
                request,
                DurabilityStatus.CANCELLED,
                PersistenceFailureCode.CLOSED,
            )
        key = (request.envelope.owner_id, request.envelope.snapshot_kind)
        existing = self._tasks.get(key)
        future: asyncio.Future[DurabilityReceipt] = asyncio.get_running_loop().create_future()
        if request.latest_state_coalescible and existing is not None and not existing.done():
            previous = self._queued.get(key)
            if previous is not None:
                previous[1].set_result(
                    self._receipt(
                        previous[0],
                        DurabilityStatus.SUPERSEDED_BY_NEWER_SNAPSHOT,
                        None,
                    )
                )
            self._queued[key] = (request, future)
            return future
        elif self.pending_task_count >= self._max_pending:
            return self._immediate(
                request,
                DurabilityStatus.PENDING_RETRY,
                PersistenceFailureCode.UNAVAILABLE,
            )
        self._queued[key] = (request, future)
        task = asyncio.create_task(
            self._run_key(key),
            name=f"snapshot-persistence:{request.request_id}",
        )
        self._tasks[key] = task
        return future

    @property
    def pending_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks.values())

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(task for task in self._tasks.values() if not task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for request, future in self._queued.values():
            if not future.done():
                future.set_result(
                    self._receipt(
                        request,
                        DurabilityStatus.CANCELLED,
                        PersistenceFailureCode.CANCELLED,
                    )
                )
        self._queued.clear()
        self._tasks.clear()

    async def _run_key(self, key: tuple[str, str]) -> None:
        try:
            while item := self._queued.pop(key, None):
                request, future = item
                receipt = await self._write(request)
                if not future.done():
                    future.set_result(receipt)
        except asyncio.CancelledError:
            return
        finally:
            current = self._tasks.get(key)
            if current is asyncio.current_task():
                self._tasks.pop(key, None)

    async def _write(self, request: SnapshotPersistenceRequest) -> DurabilityReceipt:
        try:
            for attempt in range(1, self._retry_policy.max_attempts + 1):
                try:
                    return await asyncio.to_thread(
                        self._repository.put_snapshot,
                        request.envelope,
                    )
                except PersistenceError as error:
                    if (
                        not self._retryable(error.code)
                        or attempt == self._retry_policy.max_attempts
                    ):
                        return self._receipt(request, DurabilityStatus.FAILED, error.code)
                    await asyncio.sleep(self._retry_policy.delay_for(attempt))
        except asyncio.CancelledError:
            return self._receipt(
                request,
                DurabilityStatus.CANCELLED,
                PersistenceFailureCode.CANCELLED,
            )
        return self._receipt(
            request,
            DurabilityStatus.FAILED,
            PersistenceFailureCode.UNAVAILABLE,
        )

    @staticmethod
    def _retryable(code: PersistenceFailureCode) -> bool:
        return code in {
            PersistenceFailureCode.UNAVAILABLE,
            PersistenceFailureCode.CONNECTION_FAILED,
            PersistenceFailureCode.TIMEOUT,
        }

    def _immediate(
        self,
        request: SnapshotPersistenceRequest,
        status: DurabilityStatus,
        code: PersistenceFailureCode,
    ) -> asyncio.Task[DurabilityReceipt]:
        async def result() -> DurabilityReceipt:
            return self._receipt(request, status, code)

        return asyncio.create_task(result(), name=f"snapshot-persistence:{request.request_id}")

    def _receipt(
        self,
        request: SnapshotPersistenceRequest,
        status: DurabilityStatus,
        code: PersistenceFailureCode | None,
    ) -> DurabilityReceipt:
        return DurabilityReceipt(
            request.request_id,
            request.envelope.owner_id,
            request.envelope.owner_state_revision,
            request.envelope.snapshot_id,
            status,
            failure_code=code,
        )
