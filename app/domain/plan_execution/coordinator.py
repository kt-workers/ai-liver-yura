"""計画の開始予約を活動の公開実行入口へ渡し、取消後も所有処理を回収する。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol

from app.domain.activity_execution import ActivityExecutionCoordinator, ActivityExecutionRecord

from .owner import PlanExecutionCurrentState, PlanExecutionOwner, PlanExecutionProgress


class PlanExecutionContextPort(Protocol):
    async def current_for(self, scope_id: str) -> PlanExecutionCurrentState: ...


class PlanExecutionClock(Protocol):
    def now(self) -> datetime: ...


class PlanExecutionCoordinator:
    def __init__(
        self,
        owner: PlanExecutionOwner,
        execution: ActivityExecutionCoordinator,
        context: PlanExecutionContextPort,
        clock: PlanExecutionClock,
    ) -> None:
        if owner.activity_authority is not execution.authority:
            raise ValueError("進行側と活動側の実行事実所有者が一致していません")
        self._owner = owner
        self._execution = execution
        self._context = context
        self._clock = clock
        self._tasks: dict[str, tuple[str, asyncio.Task[ActivityExecutionRecord]]] = {}
        self._cancel_requested: set[str] = set()
        self._settlements: dict[str, asyncio.Future[None]] = {}

    async def advance(self, scope_id: str) -> PlanExecutionProgress:
        current = await self._context.current_for(scope_id)
        batch = self._owner.reserve_ready(scope_id, current, self._clock.now())
        if not batch.invocations:
            return batch.progress
        tasks = {}
        settled: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        for invocation in batch.invocations:
            command_id = invocation.command.command_id
            task = asyncio.create_task(self._execution.execute(invocation))
            tasks[command_id] = task
            self._tasks[command_id] = (scope_id, task)
            self._settlements[command_id] = settled
        cancelled = False
        try:
            cancelled = await self._collect(tasks)
            cleanup = {}
            for command_id, task in tasks.items():
                record = self._owner.activity_authority.snapshot(command_id)
                if (
                    (task.cancelled() or task.exception() is not None)
                    and record is not None
                    and not record.terminal
                ):
                    cleanup[command_id] = asyncio.create_task(
                        self._execution.cancel(command_id, "plan_dispatch_failed")
                    )
            if cleanup:
                cancelled = await self._collect(cleanup, cancel_children=False) or cancelled
        finally:
            for invocation in batch.invocations:
                command_id = invocation.command.command_id
                self._owner._finish_dispatch(invocation)
                self._tasks.pop(command_id, None)
                self._cancel_requested.discard(command_id)
                self._settlements.pop(command_id, None)
            settled.set_result(None)
        if cancelled:
            raise asyncio.CancelledError
        return self._owner.progress(scope_id)

    async def stop(self, scope_id: str) -> PlanExecutionProgress:
        self._owner.stop(scope_id)
        tasks = {key: task for key, (scope, task) in self._tasks.items() if scope == scope_id}
        settlements = {self._settlements[key] for key in tasks}
        self._request_cancel(tasks)
        cancelled = await self._collect(tasks)
        if settlements:
            pending = asyncio.gather(*settlements)
            while True:
                try:
                    await asyncio.shield(pending)
                    break
                except asyncio.CancelledError:
                    cancelled = True
        if cancelled:
            raise asyncio.CancelledError
        return self._owner.progress(scope_id)

    def _request_cancel(self, tasks: dict[str, asyncio.Task[ActivityExecutionRecord]]) -> None:
        for command_id, task in tasks.items():
            if command_id not in self._cancel_requested and not task.done():
                self._cancel_requested.add(command_id)
                task.cancel()

    async def _collect(
        self,
        tasks: dict[str, asyncio.Task[ActivityExecutionRecord]],
        *,
        cancel_children: bool = True,
    ) -> bool:
        if not tasks:
            return False
        pending = asyncio.gather(*tasks.values(), return_exceptions=True)
        cancelled = False
        while True:
            try:
                await asyncio.shield(pending)
                return cancelled
            except asyncio.CancelledError:
                cancelled = True
                if cancel_children:
                    self._request_cancel(tasks)
