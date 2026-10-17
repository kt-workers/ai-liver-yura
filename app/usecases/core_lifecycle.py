"""本体の起動・停止と所有タスクの回収を、構成処理から独立して実行する。"""

from __future__ import annotations

import asyncio

from app.domain.contracts.lifecycle import (
    ApplicationShutdownError,
    ApplicationShutdownFailure,
    ApplicationShutdownStage,
)
from app.usecases.ports.core_lifecycle import AsyncClosePort, CoreLifecycleComponents
from app.usecases.task_cleanup import reap_owned_task


async def start_core(components: CoreLifecycleComponents) -> None:
    """既存の脳実行基盤を開始し、自律活動の開始失敗時は回収する。"""
    await components.brain.start()
    try:
        if components.cognition is not None and components.cognition.autonomy is not None:
            components.cognition.autonomy.start()
    except BaseException:
        await components.brain.stop()
        raise


async def stop_core(components: CoreLifecycleComponents) -> None:
    """前段の失敗でも、発話・振返り・最終保存・依存資源を回収する。"""
    try:
        try:
            await components.brain.stop()
        finally:
            if components.cognition is not None and components.cognition.speech is not None:
                await components.cognition.speech.close()
    finally:
        try:
            if components.cognition is not None and components.cognition.reflection is not None:
                await components.cognition.reflection.close()
        finally:
            await _close_core_memory(components)


async def _close_core_memory(components: CoreLifecycleComponents) -> None:
    try:
        if components.memory is not None:
            try:
                await asyncio.wait_for(
                    components.memory.close(),
                    components.config.shutdown_policy.final_persistence_grace_seconds,
                )
            except asyncio.TimeoutError:
                raise ApplicationShutdownError(
                    (
                        ApplicationShutdownFailure(
                            ApplicationShutdownStage.FINAL_PERSISTENCE, "TimeoutError"
                        ),
                    )
                ) from None
    finally:
        # 前段が失敗してもDB・再接続処理を回収する。
        await components.lifecycle.close()


class CoreActivationError(RuntimeError):
    """起動できなかった事実。外側で既存の公開失敗コードへ変換する。"""


class CoreApplicationLifecycle:
    """同じ開始・終了タスクを共有し、所有資源を一度だけ回収する。"""

    def __init__(self, core: CoreLifecycleComponents, owned: AsyncClosePort) -> None:
        self._core = core
        self._owned = owned
        self._start_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._stop_task is not None:
            raise CoreActivationError("停止済みの本体は再起動できません")
        if self._start_task is None:
            self._start_task = asyncio.create_task(start_core(self._core))
        try:
            await asyncio.shield(self._start_task)
        except BaseException as error:
            self._start_task.cancel()
            try:
                await reap_owned_task(self._start_task)
            except (Exception, asyncio.CancelledError):
                pass
            try:
                await self.stop()
            finally:
                if isinstance(error, asyncio.CancelledError):
                    raise asyncio.CancelledError from None
                raise CoreActivationError("本体の起動に失敗しました") from None

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._close())
        await reap_owned_task(self._stop_task)

    async def _close(self) -> None:
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await self._start_task
            except (Exception, asyncio.CancelledError):
                pass
        try:
            await stop_core(self._core)
        finally:
            await self._owned.close()
