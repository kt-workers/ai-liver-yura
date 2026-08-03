from __future__ import annotations

import asyncio

import pytest

import app.__main__ as app_main


class _CancelledReceiver:
    async def wait_until_stopped(self) -> None:
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_wait_until_shutdown_treats_cancel_as_expected_interrupt() -> None:
    assert await app_main._wait_until_shutdown(_CancelledReceiver()) is True


@pytest.mark.asyncio
async def test_await_runtime_shutdown_collects_cancelled_task() -> None:
    async def canceled_runtime() -> None:
        raise asyncio.CancelledError

    task = asyncio.create_task(canceled_runtime())

    assert await app_main._await_runtime_shutdown(task) is True


def test_main_swallows_top_level_cancelled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def canceled_run(coroutine: object) -> None:
        close = getattr(coroutine, "close")
        close()
        raise asyncio.CancelledError

    monkeypatch.setattr(app_main.asyncio, "run", canceled_run)

    app_main.main()
