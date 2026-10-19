"""生成済み資源の終了操作を、構成や提供元に依存せず回収する。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class OwnedResourcesCloseError(RuntimeError):
    """全資源の回収を試みたが、少なくとも一件の終了操作が失敗した。"""


class OwnedResourceLedger:
    """生成済み資源だけを逆順に、一度だけ回収する台帳。"""

    def __init__(self) -> None:
        self.actions: list[Callable[[], Awaitable[None]]] = []

    def add_sync(self, operation: Callable[[], None]) -> None:
        async def close() -> None:
            operation()

        self.actions.append(close)

    async def close(self) -> None:
        failed = False
        cancelled = False
        while self.actions:
            try:
                await self.actions.pop()()
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failed = True
        if cancelled:
            raise asyncio.CancelledError
        if failed:
            raise OwnedResourcesCloseError("所有資源の終了処理に失敗しました")
