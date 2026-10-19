"""DBを使わず、受付済み保存操作の所有・上限・取消・終了回収を検証する。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar, cast

import pytest

from app.domain.contracts.persistence import (
    PersistenceError,
    PersistenceFailureCode,
    PersistenceOperationResult,
)
from app.usecases.persistence_tasks import BoundedPersistenceWorkOwner, CoreMemoryOperation

T = TypeVar("T")


class WorkOwner(BoundedPersistenceWorkOwner):
    """試験用の要求入口。実際の受付・回収処理は本番クラスを使う。"""

    def submit(
        self, action: Callable[[], Coroutine[Any, Any, PersistenceOperationResult[T]]]
    ) -> CoreMemoryOperation[T]:
        return self._submit(action)


async def turn() -> None:
    continued = asyncio.Event()
    asyncio.get_running_loop().call_soon(continued.set)
    await continued.wait()


@pytest.mark.parametrize("limit", [0, -1, 257, True, "1", None])
def test_invalid_capacity_is_rejected(limit: object) -> None:
    with pytest.raises(ValueError):
        WorkOwner(max_pending=cast(int, limit))


@pytest.mark.asyncio
@pytest.mark.parametrize("completed_first", [False, True])
@pytest.mark.parametrize(
    "code", [None, PersistenceFailureCode.CONNECTION_FAILED, PersistenceFailureCode.CANCELLED]
)
async def test_result_identity_is_preserved_for_repeated_waiters(
    completed_first: bool, code: PersistenceFailureCode | None
) -> None:
    owner = WorkOwner(max_pending=1)
    expected: PersistenceOperationResult[int] = PersistenceOperationResult(
        23 if code is None else None, code
    )

    async def work() -> PersistenceOperationResult[int]:
        return expected

    operation = owner.submit(work)
    if completed_first:
        await turn()
    first, second = await asyncio.gather(operation.wait(), operation.wait())
    assert first is second is operation.result() is expected
    assert operation.done
    await owner.close()
    assert owner.pending_count == 0


@pytest.mark.asyncio
async def test_queue_rejection_does_not_construct_an_unowned_coroutine() -> None:
    owner = WorkOwner(max_pending=1)
    entered, release = asyncio.Event(), asyncio.Event()
    constructed: list[str] = []

    async def work() -> PersistenceOperationResult[int]:
        entered.set()
        await release.wait()
        return PersistenceOperationResult(7)

    def build() -> Coroutine[Any, Any, PersistenceOperationResult[int]]:
        constructed.append("build")
        return work()

    operation = owner.submit(build)
    try:
        await entered.wait()
        with pytest.raises(PersistenceError) as caught:
            owner.submit(build)
        assert caught.value.code is PersistenceFailureCode.UNAVAILABLE
        assert constructed == ["build"]
        assert owner.pending_count == 1
    finally:
        release.set()
        await owner.close()
    assert (await operation.wait()).value == 7
    assert owner.pending_count == 0
    with pytest.raises(PersistenceError) as caught:
        owner.submit(build)
    assert caught.value.code is PersistenceFailureCode.CLOSED
    assert constructed == ["build"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_repeated_waiter_cancellation_does_not_cancel_admitted_work(fails: bool) -> None:
    owner = WorkOwner(max_pending=1)
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    failure = RuntimeError("保存処理の試験用失敗")

    async def work() -> PersistenceOperationResult[int]:
        entered.set()
        try:
            await release.wait()
            if fails:
                raise failure
            return PersistenceOperationResult(8)
        finally:
            finished.set()

    operation = owner.submit(work)
    waiter = asyncio.create_task(operation.wait())
    try:
        await entered.wait()
        await turn()
        for _ in range(3):
            assert waiter.cancel()
            await turn()
            assert not waiter.done()
            assert not operation.done
            assert not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(waiter), 1.0)
        assert operation.done and finished.is_set()
        if fails:
            with pytest.raises(RuntimeError) as caught:
                operation.result()
            assert caught.value is failure
        else:
            assert operation.result().value == 8
    finally:
        release.set()
        await asyncio.gather(waiter, return_exceptions=True)
        await owner.close()
    assert owner.pending_count == 0


@pytest.mark.asyncio
async def test_operation_failure_is_retrievable_after_owner_close() -> None:
    owner = WorkOwner(max_pending=1)
    failure = RuntimeError("保存処理の試験用失敗")

    async def work() -> PersistenceOperationResult[int]:
        raise failure

    operation = owner.submit(work)
    await owner.close()
    assert owner.pending_count == 0
    assert operation.done
    for _ in range(2):
        with pytest.raises(RuntimeError) as caught:
            await operation.wait()
        assert caught.value is failure


@pytest.mark.asyncio
async def test_owner_drains_even_when_work_itself_is_cancelled() -> None:
    owner = WorkOwner(max_pending=1)

    async def work() -> PersistenceOperationResult[int]:
        raise asyncio.CancelledError

    operation = owner.submit(work)
    await owner.close()
    assert operation.done
    assert owner.pending_count == 0
    with pytest.raises(asyncio.CancelledError):
        await operation.wait()


@pytest.mark.asyncio
async def test_concurrent_close_shares_drain_and_preserves_callers_cancellation() -> None:
    owner = WorkOwner(max_pending=1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def work() -> PersistenceOperationResult[int]:
        entered.set()
        await release.wait()
        return PersistenceOperationResult(9)

    operation = owner.submit(work)
    await entered.wait()
    first, second = asyncio.create_task(owner.close()), asyncio.create_task(owner.close())
    try:
        await turn()
        drain = owner._close_task
        assert drain is not None
        first.cancel()
        await turn()
        first.cancel()
        await turn()
        assert owner._close_task is drain
        assert not first.done() and not second.done() and not operation.done
        with pytest.raises(PersistenceError) as caught:
            owner.submit(work)
        assert caught.value.code is PersistenceFailureCode.CLOSED
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(first, second, return_exceptions=True), 1.0
        )
        assert isinstance(results[0], asyncio.CancelledError)
        assert results[1] is None
        assert operation.result().value == 9
        assert owner.pending_count == 0
        await owner.close()
        assert owner._close_task is drain
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await owner.close()


@pytest.mark.asyncio
async def test_completed_operation_releases_capacity() -> None:
    owner = WorkOwner(max_pending=1)

    async def work() -> PersistenceOperationResult[int]:
        return PersistenceOperationResult(10)

    first = owner.submit(work)
    await first.wait()
    await turn()
    second = owner.submit(work)
    assert (await second.wait()).value == 10
    await owner.close()
    assert owner.pending_count == 0
