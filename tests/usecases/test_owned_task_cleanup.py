"""所有タスクを取り残さず、失敗と呼出し側の取消を区別して伝える。"""

from __future__ import annotations

import asyncio

import pytest

from app.usecases.task_cleanup import reap_owned_task


async def _turn() -> None:
    """壁時計に依存せず、予約済みの処理へ実行を譲る。"""
    continued = asyncio.Event()
    asyncio.get_running_loop().call_soon(continued.set)
    await continued.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("already_done", [False, True])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_owned_terminal_outcome_is_preserved(outcome: str, already_done: bool) -> None:
    failure = RuntimeError("owned cleanup failed")

    async def cleanup() -> int:
        if outcome == "failure":
            raise failure
        if outcome == "cancelled":
            raise asyncio.CancelledError
        return 17

    owned = asyncio.create_task(cleanup())
    try:
        if already_done:
            await asyncio.gather(owned, return_exceptions=True)
        if outcome == "failure":
            with pytest.raises(RuntimeError) as caught:
                await reap_owned_task(owned)
            assert caught.value is failure
        elif outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await reap_owned_task(owned)
        else:
            await reap_owned_task(owned)
            assert owned.result() == 17
        assert owned.done()
    finally:
        await asyncio.gather(owned, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("fails_after_release", [False, True])
async def test_repeated_caller_cancellation_waits_for_owned_cleanup(
    fails_after_release: bool,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    failure = RuntimeError("owned failure after caller cancellation")

    async def cleanup() -> None:
        started.set()
        try:
            await release.wait()
            if fails_after_release:
                raise failure
        finally:
            finished.set()

    owned = asyncio.create_task(cleanup())
    await started.wait()
    waiter = asyncio.create_task(reap_owned_task(owned))
    try:
        await _turn()
        for _ in range(3):
            assert waiter.cancel()
            await _turn()
            assert not waiter.done()
            assert not owned.done()
            assert not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(waiter), timeout=1.0)
        assert finished.is_set()
        assert owned.done()
        assert not owned.cancelled()
        assert owned.exception() is (failure if fails_after_release else None)
    finally:
        release.set()
        await asyncio.gather(waiter, owned, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_reaches_the_owner_only_when_explicitly_requested() -> None:
    started = asyncio.Event()
    finished = asyncio.Event()
    block = asyncio.Event()

    async def cleanup() -> None:
        started.set()
        try:
            await block.wait()
        finally:
            finished.set()

    owned = asyncio.create_task(cleanup())
    await started.wait()
    waiter = asyncio.create_task(reap_owned_task(owned))
    try:
        await _turn()
        owned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(waiter), timeout=1.0)
        assert owned.cancelled()
        assert finished.is_set()
    finally:
        block.set()
        await asyncio.gather(waiter, owned, return_exceptions=True)
