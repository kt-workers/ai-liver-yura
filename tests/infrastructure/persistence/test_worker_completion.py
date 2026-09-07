"""保存待ちの容量超過と終了要求でも、受理済み要求の結果を失わない。"""

import asyncio
from threading import Event

from app.infrastructure.persistence import (
    DurabilityReceipt,
    DurabilityStatus,
    InMemoryLifecycleSnapshotRepository,
    PersistenceSnapshotEnvelope,
    SnapshotPersistenceRequest,
    SnapshotPersistenceWorker,
)
from tests.infrastructure.persistence.test_lifecycle_snapshots import NOW, envelope


class ControlledRepository(InMemoryLifecycleSnapshotRepository):
    def __init__(self) -> None:
        super().__init__(lambda: NOW)
        self.started = Event()
        self.release = Event()
        self.finished = Event()

    def put_snapshot(
        self, item: PersistenceSnapshotEnvelope, *, expected_revision: int | None = None
    ) -> DurabilityReceipt:
        self.started.set()
        assert self.release.wait(2), "試験の保存待機が解放されませんでした"
        try:
            return super().put_snapshot(item, expected_revision=expected_revision)
        finally:
            self.finished.set()


async def wait_started(repository: ControlledRepository) -> None:
    async def wait() -> None:
        while not repository.started.is_set():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(wait(), 1)


def request(index: int, coalescible: bool = False) -> SnapshotPersistenceRequest:
    return SnapshotPersistenceRequest(
        f"request-{index}", envelope(f"snapshot-{index}", index), coalescible
    )


def test_capacity_rejection_keeps_already_accepted_queue() -> None:
    async def run() -> None:
        repository = ControlledRepository()
        worker = SnapshotPersistenceWorker(repository, max_pending=2)
        first = worker.submit(request(1))
        await wait_started(repository)
        second = worker.submit(request(2))
        rejected = worker.submit(request(3))
        try:
            assert (await rejected).status is DurabilityStatus.PENDING_RETRY
            repository.release.set()
            receipts = await asyncio.wait_for(asyncio.gather(first, second), 1)
            assert [r.status for r in receipts] == [DurabilityStatus.DURABLE] * 2
            assert [r.persistence_request_id for r in receipts] == ["request-1", "request-2"]
        finally:
            repository.release.set()
            await worker.close()

    asyncio.run(run())


def test_coalescible_request_does_not_bypass_full_capacity() -> None:
    async def run() -> None:
        repository = ControlledRepository()
        worker = SnapshotPersistenceWorker(repository, max_pending=1)
        first = worker.submit(request(1))
        await wait_started(repository)
        second = worker.submit(request(2, True))
        try:
            await asyncio.sleep(0)
            assert second.done(), "統合対象がない要求は満杯の待ち行列へ追加できません"
            assert second.result().status is DurabilityStatus.PENDING_RETRY
        finally:
            repository.release.set()
            await first
            await worker.close()

    asyncio.run(run())


def test_close_collects_running_write_and_reports_committed_truth() -> None:
    async def run() -> None:
        repository = ControlledRepository()
        worker = SnapshotPersistenceWorker(repository)
        first = worker.submit(request(1))
        await wait_started(repository)
        queued = worker.submit(request(2))
        closing = asyncio.create_task(worker.close())
        try:
            await asyncio.sleep(0.02)
            assert not closing.done(), "同期保存を残したまま終了を報告しました"
            assert not first.done() and not repository.finished.is_set()
            repository.release.set()
            await asyncio.wait_for(closing, 1)
            assert repository.finished.is_set()
            assert first.result().status is DurabilityStatus.DURABLE
            assert first.result().persistence_request_id == "request-1"
            assert queued.result().status is DurabilityStatus.CANCELLED
            assert worker.pending_task_count == 0
            assert repository.get_latest("goals", "goal_commitment") is not None
        finally:
            repository.release.set()
            await closing
            await worker.close()

    asyncio.run(run())


def test_older_coalescible_request_does_not_discard_newer_queued_state() -> None:
    async def run() -> None:
        repository = ControlledRepository()
        worker = SnapshotPersistenceWorker(repository, max_pending=2)
        first = worker.submit(request(1))
        await wait_started(repository)
        newer = worker.submit(request(3, True))
        older = worker.submit(request(2, True))
        try:
            receipt = await older
            assert receipt.status is DurabilityStatus.SUPERSEDED_BY_NEWER_SNAPSHOT
            repository.release.set()
            assert (await newer).status is DurabilityStatus.DURABLE
            await first
            latest = repository.get_latest("goals", "goal_commitment")
            assert latest is not None and latest.owner_state_revision == 3
        finally:
            repository.release.set()
            await worker.close()

    asyncio.run(run())
