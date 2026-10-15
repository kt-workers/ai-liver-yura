"""構成済みCoreをユースケースのライフサイクル契約で実行する。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.bootstrap.core_components import CoreComponents
from app.usecases.core_lifecycle import start_core, stop_core
from app.usecases.task_cleanup import reap_owned_task


class CoreRuntimeApplication:
    """構成データと実行ライフサイクルを分離して公開するアプリケーション。"""

    def __init__(self, components: CoreComponents) -> None:
        self._components = components
        self._start_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None

    def __getattr__(self, name: str) -> Any:
        # 構成値はCoreComponentsが所有し、実行状態はこの境界が所有する。
        return getattr(self._components, name)

    async def start(self) -> None:
        if self._stop_task is not None:
            raise RuntimeError("停止開始後のCoreは再起動できません")
        if self._start_task is None:
            self._start_task = asyncio.create_task(start_core(self._components))
        try:
            await asyncio.shield(self._start_task)
        except asyncio.CancelledError:
            if not self._start_task.done():
                self._start_task.cancel()
            try:
                await reap_owned_task(self._start_task)
            except (asyncio.CancelledError, Exception):
                pass
            await self.stop()
            raise
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_owned())
        await reap_owned_task(self._stop_task)

    async def _stop_owned(self) -> None:
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await reap_owned_task(self._start_task)
            except (asyncio.CancelledError, Exception):
                pass
        await stop_core(self._components)
