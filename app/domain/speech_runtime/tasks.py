from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CandidateTaskKey:
    candidate_id: str
    generation: int
    role: str

    def __post_init__(self) -> None:
        if (
            not self.candidate_id
            or not self.role
            or type(self.generation) is not int
            or self.generation < 1
        ):
            raise ValueError("candidate task key が不正です")


class CandidateTaskRegistry:
    """global cancellationではなくcandidate/generation単位で非同期作業を隔離する。"""

    def __init__(self) -> None:
        self._tasks: dict[CandidateTaskKey, asyncio.Task[object]] = {}

    @property
    def pending_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks.values())

    def has_pending_candidate_work(
        self, candidate_id: str, generation: int, *, excluding_role: str | None = None
    ) -> bool:
        """admission hold以外のcandidate局所Roleが未完了かを返す。"""
        return any(
            key.candidate_id == candidate_id
            and key.generation == generation
            and key.role != excluding_role
            and not task.done()
            for key, task in self._tasks.items()
        )

    def start(
        self, key: CandidateTaskKey, work: Coroutine[Any, Any, object]
    ) -> asyncio.Task[object]:
        if key in self._tasks and not self._tasks[key].done():
            raise ValueError("candidate taskは重複できません")
        task: asyncio.Task[object] = asyncio.create_task(work)
        self._tasks[key] = task
        task.add_done_callback(lambda _: self._tasks.pop(key, None))
        return task

    async def cancel_candidate(
        self, candidate_id: str, *, before_generation: int | None = None
    ) -> None:
        selected = tuple(
            task
            for key, task in self._tasks.items()
            if key.candidate_id == candidate_id
            and (before_generation is None or key.generation < before_generation)
        )
        for task in selected:
            task.cancel()
        if selected:
            await asyncio.gather(*selected, return_exceptions=True)

    async def shutdown(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
