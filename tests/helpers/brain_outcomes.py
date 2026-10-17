"""並行Brainの公開結果を誤帰属させず、指定された終了結果を観測する。"""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.usecases.brain_integration_runtime import (
    BrainIntegrationRuntime,
    BrainIntegrationWorkOutcome,
)


@dataclass
class _Inbox:
    """Brain単位で未照合結果を保持し、複数の待受による取り違えを防ぐ。"""

    pending: list[BrainIntegrationWorkOutcome] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_inboxes: WeakKeyDictionary[BrainIntegrationRuntime, _Inbox] = WeakKeyDictionary()


def _matches(
    outcome: BrainIntegrationWorkOutcome,
    *,
    work_id: str | None,
    trace_id: str | None,
    module: BrainIntegrationModule | None,
    status: BrainWorkStatus | None,
) -> bool:
    return (
        (work_id is None or outcome.work_id == work_id)
        and (trace_id is None or outcome.trace_id == trace_id)
        and (module is None or outcome.module is module)
        and (status is None or outcome.status is status)
    )


async def next_outcome_matching(
    brain: BrainIntegrationRuntime,
    *,
    work_id: str | None = None,
    trace_id: str | None = None,
    module: BrainIntegrationModule | None = None,
    status: BrainWorkStatus | None = None,
    timeout: float = 2.0,
) -> BrainIntegrationWorkOutcome:
    """条件が一致する公開結果を返す。対象外は次回の照合に保持する。"""
    if all(value is None for value in (work_id, trace_id, module, status)):
        raise ValueError("照合するwork・trace・module・statusを指定してください")
    if timeout <= 0:
        raise ValueError("期限は正の有限秒でなければなりません")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    inbox = _inboxes.get(brain)
    if inbox is None:
        inbox = _Inbox()
        _inboxes[brain] = inbox
    async with inbox.lock:
        while True:
            for index, cached in enumerate(inbox.pending):
                if _matches(
                    cached, work_id=work_id, trace_id=trace_id,
                    module=module, status=status,
                ):
                    return inbox.pending.pop(index)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError("対象Brain結果が期限内に届きません")
            outcome = await asyncio.wait_for(brain.next_outcome(), remaining)
            if _matches(
                outcome, work_id=work_id, trace_id=trace_id,
                module=module, status=status,
            ):
                return outcome
            inbox.pending.append(outcome)


async def collect_work_outcomes(
    brain: BrainIntegrationRuntime,
    work_ids: Collection[str],
    *,
    timeout: float = 2.0,
) -> tuple[BrainIntegrationWorkOutcome, ...]:
    """複数workに一つの有限期限を適用し、対象外の結果は保持する。"""
    pending = set(work_ids)
    if not pending or len(pending) != len(work_ids) or timeout <= 0:
        raise ValueError("重複しない対象workと正の期限が必要です")
    deadline = asyncio.get_running_loop().time() + timeout
    observed: list[BrainIntegrationWorkOutcome] = []
    for work_id in work_ids:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError("対象workの結果が期限内に届きません")
        observed.append(await next_outcome_matching(brain, work_id=work_id, timeout=remaining))
    return tuple(observed)


async def wait_for_work_outcome(
    brain: BrainIntegrationRuntime,
    work_id: str,
    *,
    timeout: float = 2.0,
) -> BrainIntegrationWorkOutcome:
    """指定workの公開済み終端を取得する。"""
    return await next_outcome_matching(brain, work_id=work_id, timeout=timeout)
