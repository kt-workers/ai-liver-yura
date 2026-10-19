"""所有済みタスクの終了を回収し、呼出し側の取消を維持する。"""

from __future__ import annotations

import asyncio
from typing import TypeVar

_CleanupResult = TypeVar("_CleanupResult")


async def reap_owned_task(task: asyncio.Task[_CleanupResult]) -> None:
    """呼出し側の再取消でも所有する終了処理を最後まで回収する。"""
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
    task.result()
