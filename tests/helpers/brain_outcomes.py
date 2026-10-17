"""並行Brainの公開結果から指定した入力workの終端だけを観測する。"""

from __future__ import annotations

import asyncio
from collections.abc import Collection

from app.usecases.brain_integration_runtime import (
    BrainIntegrationRuntime,
    BrainIntegrationWorkOutcome,
)


async def collect_work_outcomes(
    brain: BrainIntegrationRuntime,
    work_ids: Collection[str],
    *,
    timeout: float = 2.0,
) -> tuple[BrainIntegrationWorkOutcome, ...]:
    """起動時評価を対象workに取り違えず、全体の期限を共有する。"""
    pending = set(work_ids)
    if not pending or len(pending) != len(work_ids) or timeout <= 0:
        raise ValueError("対象workと有限の期限が必要です")
    deadline = asyncio.get_running_loop().time() + timeout
    observed: list[BrainIntegrationWorkOutcome] = []
    while pending:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError("対象workの結果が期限内に届きません")
        outcome = await asyncio.wait_for(brain.next_outcome(), remaining)
        if outcome.work_id not in pending:
            continue
        pending.remove(outcome.work_id)
        observed.append(outcome)
    return tuple(observed)


async def wait_for_work_outcome(
    brain: BrainIntegrationRuntime,
    work_id: str,
    *,
    timeout: float = 2.0,
) -> BrainIntegrationWorkOutcome:
    """指定workの公開済み終端を取得する。"""
    return (await collect_work_outcomes(brain, (work_id,), timeout=timeout))[0]
