"""本体の記憶操作を既存所有者へ渡し、取消後も確定結果を取得可能にする。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Generic, TypeVar, cast

from app.domain.memory import MemoryRelationKind, MemoryWriteRequest, MemoryWriteResult
from app.domain.memory.contracts import MemoryRetrievalQuery
from app.domain.memory.ranking import RankedMemoryEvidenceView
from app.domain.memory_reflection import ReflectionCandidateResult
from app.infrastructure.persistence import (
    PersistenceError,
    PersistenceFailureCode,
    PersistenceOperationResult,
    PostgresPersistenceRuntime,
)

T = TypeVar("T")


async def _reap(task: asyncio.Future[T]) -> T:
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


class CoreMemoryOperation(Generic[T]):
    """呼出しの取消と保存結果を分ける、呼出し元が保持する操作参照。"""

    def __init__(self, task: asyncio.Task[PersistenceOperationResult[T]]) -> None:
        self._task = task

    async def wait(self) -> PersistenceOperationResult[T]:
        return await _reap(self._task)

    def result(self) -> PersistenceOperationResult[T]:
        return self._task.result()

    @property
    def done(self) -> bool:
        return self._task.done()


class CoreMemoryPersistenceBinding:
    def __init__(self, persistence: PostgresPersistenceRuntime, *, max_pending: int) -> None:
        if not isinstance(persistence, PostgresPersistenceRuntime):
            raise ValueError("記憶保存にはPostgresPersistenceRuntimeが必要です")
        if type(max_pending) is not int or not 1 <= max_pending <= 256:
            raise ValueError("記憶操作の受付件数上限が不正です")
        self._persistence = persistence
        self._max_pending = max_pending
        self._pending: set[asyncio.Task[object]] = set()
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    def submit_write(self, request: MemoryWriteRequest) -> CoreMemoryOperation[MemoryWriteResult]:
        if not isinstance(request, MemoryWriteRequest):
            raise ValueError("記憶書込みには型付き要求が必要です")
        return self._submit(lambda: self._persistence.write_memory(request))

    def submit_reflection(
        self,
        result: ReflectionCandidateResult,
        *,
        expected_revision: int | None = None,
        target_memory_id: str | None = None,
        relation_kind: MemoryRelationKind | None = None,
    ) -> CoreMemoryOperation[MemoryWriteResult] | None:
        if not isinstance(result, ReflectionCandidateResult):
            raise ValueError("振り返り所有者の型付き結果が必要です")
        if result.candidate is None:
            return None
        return self.submit_write(
            MemoryWriteRequest(result.candidate, expected_revision, target_memory_id, relation_kind)
        )

    def submit_retrieval(
        self, query: MemoryRetrievalQuery
    ) -> CoreMemoryOperation[RankedMemoryEvidenceView]:
        if not isinstance(query, MemoryRetrievalQuery):
            raise ValueError("記憶検索には型付き要求が必要です")
        return self._submit(lambda: self._persistence.retrieve_memory(query))

    def _submit(
        self, action: Callable[[], Coroutine[Any, Any, PersistenceOperationResult[T]]]
    ) -> CoreMemoryOperation[T]:
        if self._closed:
            raise PersistenceError(PersistenceFailureCode.CLOSED, "記憶操作の受付は終了しました")
        if len(self._pending) >= self._max_pending:
            raise PersistenceError(
                PersistenceFailureCode.UNAVAILABLE, "記憶操作の受付件数が上限へ到達しました"
            )
        loop = asyncio.get_running_loop()
        task = loop.create_task(action())
        self._pending.add(cast(asyncio.Task[object], task))
        task.add_done_callback(self._finished)
        return CoreMemoryOperation(task)

    def _finished(self, task: asyncio.Task[object]) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close())
        await _reap(self._close_task)

    async def _close(self) -> None:
        if self._pending:
            await asyncio.gather(*tuple(self._pending), return_exceptions=True)
