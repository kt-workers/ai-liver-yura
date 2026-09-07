"""DB処理を実行ループから分離し、起動・結果・終了の資源を一箇所で所有する。"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from app.domain.goals.contracts import GoalCommitmentSnapshot
from app.domain.memory import MemoryStoreAuthority, MemoryWriteRequest, MemoryWriteResult
from app.domain.memory.contracts import MemoryRetrievalQuery
from app.domain.memory.ranking import MemoryRetrievalRankingPolicy, RankedMemoryEvidenceView
from app.runtime.lifecycle import DependencyFailure, DependencyRetryPolicy, RuntimeLifecycle

from .contracts import (
    DurabilityReceipt,
    PersistenceAvailability,
    PersistenceError,
    PersistenceFailureCode,
)
from .goal_snapshot_codec import (
    OWNER_ID,
    SNAPSHOT_KIND,
    decode_goal_snapshot,
    encode_goal_snapshot,
)
from .postgresql_connection import PostgresConnectionPolicy, PostgresDatabase, PostgresEndpoint
from .postgresql_memory import PostgresMemoryRepository
from .postgresql_snapshots import PostgresLifecycleSnapshotRepository
from .worker import (
    SnapshotPersistenceRequest,
    SnapshotPersistenceRetryPolicy,
    SnapshotPersistenceWorker,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PersistenceOperationResult(Generic[T]):
    """呼出しの成功値と保存機構の失敗を区別する。生の提供元例外は運ばない。"""

    value: T | None
    failure_code: PersistenceFailureCode | None = None

    def __post_init__(self) -> None:
        if self.failure_code is not None and (
            self.value is not None or not isinstance(self.failure_code, PersistenceFailureCode)
        ):
            raise ValueError("保存処理の成功値と失敗分類が矛盾しています")


class PostgresPersistenceRuntime:
    """構成側から接続先を受け取り、同期所有者とDBを上限付きの実行群で呼ぶ。"""

    def __init__(
        self,
        endpoint: PostgresEndpoint,
        connection_policy: PostgresConnectionPolicy,
        ranking_policy: MemoryRetrievalRankingPolicy,
        *,
        max_pending: int,
        snapshot_retry_policy: SnapshotPersistenceRetryPolicy,
    ) -> None:
        if type(max_pending) is not int or not 1 <= max_pending <= 256:
            raise ValueError("保存処理の待ち件数上限が不正です")
        self._endpoint = endpoint
        self._connection_policy = connection_policy
        self._ranking_policy = ranking_policy
        self._max_pending = max_pending
        self._snapshot_retry_policy = snapshot_retry_policy
        self._executor = ThreadPoolExecutor(
            max_workers=connection_policy.max_connections, thread_name_prefix="yura-persistence"
        )
        self._database: PostgresDatabase | None = None
        self._memory: MemoryStoreAuthority | None = None
        self._snapshots: PostgresLifecycleSnapshotRepository | None = None
        self._worker: SnapshotPersistenceWorker | None = None
        self._pending: set[asyncio.Future[object]] = set()
        self._lifecycle: RuntimeLifecycle | None = None
        self._dependency_id: str | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self.availability = PersistenceAvailability.UNAVAILABLE

    def attach(self, lifecycle: RuntimeLifecycle, retry_policy: DependencyRetryPolicy) -> None:
        if self._lifecycle is not None or self._closed:
            raise ValueError("永続化の起動停止接続は一度だけ登録できます")
        lifecycle.register_dependency(retry_policy, reconnect=self.start, close=self.close)
        self._lifecycle = lifecycle
        self._dependency_id = retry_policy.dependency_id

    async def start(self) -> DependencyFailure | None:
        async with self._start_lock:
            if self._closed:
                return DependencyFailure(PersistenceFailureCode.CLOSED.value, False)
            if self._database is not None:
                # 再接続では現在の所有者や実行群を置き換えない。
                result = await self._run(self._probe)
            else:
                result = await self._run(self._open)
            if result.failure_code is not None:
                return self._failure(result.failure_code)
            if self._closed:
                return DependencyFailure(PersistenceFailureCode.CLOSED.value, False)
            self.availability = PersistenceAvailability.AVAILABLE
            if self._worker is None:
                assert self._snapshots is not None
                self._worker = SnapshotPersistenceWorker(
                    self._snapshots,
                    max_pending=self._max_pending,
                    retry_policy=self._snapshot_retry_policy,
                )
            return None

    def _open(self) -> None:
        database = PostgresDatabase.connect(self._endpoint, self._connection_policy)
        try:
            memory = PostgresMemoryRepository(database)
            snapshots = PostgresLifecycleSnapshotRepository(database)
            memory.migrate()
            snapshots.migrate()
        except BaseException:
            database.close()
            raise
        self._database = database
        self._snapshots = snapshots
        self._memory = MemoryStoreAuthority(memory, ranking_policy=self._ranking_policy)

    def _probe(self) -> None:
        assert self._database is not None
        with self._database.transaction() as connection:
            connection.execute("SELECT 1")

    async def write_memory(
        self,
        request: MemoryWriteRequest,
    ) -> PersistenceOperationResult[MemoryWriteResult]:
        owner = self._memory
        if owner is None:
            return PersistenceOperationResult(None, self._unavailable_code())
        return await self._run(lambda: owner.write(request))

    async def retrieve_memory(
        self,
        query: MemoryRetrievalQuery,
    ) -> PersistenceOperationResult[RankedMemoryEvidenceView]:
        owner = self._memory
        if owner is None:
            return PersistenceOperationResult(None, self._unavailable_code())
        return await self._run(lambda: owner.retrieve(query))

    async def restore_goals(self) -> PersistenceOperationResult[GoalCommitmentSnapshot]:
        repository = self._snapshots
        if repository is None:
            return PersistenceOperationResult(None, self._unavailable_code())

        def read() -> GoalCommitmentSnapshot | None:
            candidate = repository.get_latest(OWNER_ID, SNAPSHOT_KIND)
            return None if candidate is None else decode_goal_snapshot(candidate)

        result = await self._run(read)
        return PersistenceOperationResult(result.value, result.failure_code)

    def persist_goals(
        self,
        snapshot: GoalCommitmentSnapshot,
        *,
        request_id: str,
        runtime_epoch: str,
    ) -> asyncio.Future[DurabilityReceipt]:
        if self._closed or self._worker is None:
            raise PersistenceError(self._unavailable_code(), "状態保存を受け付けられません")
        # 呼出し側はGoalCommitmentStore.applyが返した後、ロック外で渡す。
        item = encode_goal_snapshot(snapshot, snapshot_id=request_id, runtime_epoch=runtime_epoch)
        future = self._worker.submit(SnapshotPersistenceRequest(request_id, item, True))
        future.add_done_callback(self._record_receipt)
        return future

    def _record_receipt(self, future: asyncio.Future[DurabilityReceipt]) -> None:
        if not future.cancelled() and future.exception() is None:
            code = future.result().failure_code
            if code is not None:
                self._report_failure(code)

    async def _run(self, action: Callable[[], T]) -> PersistenceOperationResult[T]:
        if self._closed:
            return PersistenceOperationResult(None, PersistenceFailureCode.CLOSED)
        if len(self._pending) >= self._max_pending:
            return PersistenceOperationResult(None, PersistenceFailureCode.UNAVAILABLE)
        future = asyncio.get_running_loop().run_in_executor(self._executor, action)
        self._pending.add(cast(asyncio.Future[object], future))
        try:
            value = await _settle(future)
            result: PersistenceOperationResult[T] = PersistenceOperationResult(value)
            return result
        except PersistenceError as error:
            self._report_failure(error.code)
            return PersistenceOperationResult(None, error.code)
        finally:
            self._pending.discard(future)

    @property
    def pending_task_count(self) -> int:
        return len(self._pending) + (self._worker.pending_task_count if self._worker else 0)

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close(), name="persistence-close")
        await _settle(self._close_task)

    async def _close(self) -> None:
        try:
            if self._worker is not None:
                await self._worker.close()
        finally:
            try:
                if self._pending:
                    await asyncio.gather(*tuple(self._pending), return_exceptions=True)
            finally:
                try:
                    if self._database is not None:
                        await asyncio.get_running_loop().run_in_executor(
                            self._executor, self._database.close
                        )
                finally:
                    # 実行中処理の回収後なので、この終了はDB待機を含まない。
                    self._executor.shutdown(wait=True)
                    self.availability = PersistenceAvailability.CLOSED

    def _unavailable_code(self) -> PersistenceFailureCode:
        return PersistenceFailureCode.CLOSED if self._closed else PersistenceFailureCode.UNAVAILABLE

    @staticmethod
    def _failure(code: PersistenceFailureCode) -> DependencyFailure:
        return DependencyFailure(
            code.value,
            code
            in {
                PersistenceFailureCode.UNAVAILABLE,
                PersistenceFailureCode.CONNECTION_FAILED,
                PersistenceFailureCode.TIMEOUT,
            },
        )

    def _report_failure(self, code: PersistenceFailureCode) -> None:
        if self._closed or code in {
            PersistenceFailureCode.PERSISTENCE_CONFLICT,
            PersistenceFailureCode.CONSTRAINT_VIOLATION,
            PersistenceFailureCode.INCOMPATIBLE_PAYLOAD_VERSION,
            PersistenceFailureCode.CORRUPT_RECORD,
            PersistenceFailureCode.INTEGRITY_FAILED,
            PersistenceFailureCode.CANCELLED,
        }:
            return
        self.availability = PersistenceAvailability.DEGRADED
        if self._lifecycle is not None and self._dependency_id is not None:
            self._lifecycle.report_failure(self._dependency_id, self._failure(code))
            self._lifecycle.schedule_reconnect(self._dependency_id)


async def _settle(future: asyncio.Future[T]) -> T:
    """取消後も実行中I/Oを回収し、例外を未取得のまま残さない。"""
    cancelled = False
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not future.cancelled():
            future.exception()
        raise asyncio.CancelledError
    return future.result()
