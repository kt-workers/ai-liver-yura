"""Brainの非直列終端をtrace/module/work単位で取得する試験ヘルパー。"""

from __future__ import annotations

import asyncio
import weakref

from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.usecases.brain_integration_runtime import (
    BrainIntegrationRuntime,
    BrainIntegrationWorkOutcome,
)


_BUFFERS: weakref.WeakKeyDictionary[
    BrainIntegrationRuntime, list[BrainIntegrationWorkOutcome]
] = WeakKeyDictionary()


def _matches(
    outcome: BrainIntegrationWorkOutcome,
    *,
    trace_id: str | None,
    module: BrainIntegrationModule | None,
    work_id: str | None,
    status: BrainWorkStatus | None,
) -> bool:
    return (
        (trace_id is None or outcome.trace_id == trace_id)
        and (module is None or outcome.module is module)
        and (work_id is None or outcome.work_id == work_id)
        and (status is None or outcome.status is status)
    )


async def next_outcome_matching(
    brain: BrainIntegrationRuntime,
    *,
    trace_id: str | None = None,
    module: BrainIntegrationModule | None = None,
    work_id: str | None = None,
    status: BrainWorkStatus | None = None,
    timeout: float = 2.0,
) -> BrainIntegrationWorkOutcome:
    """到着順を仮定せず、識別情報に一致する終端を順序を保って返す。"""
    buffered = _BUFFERS.setdefault(brain, [])
    for index, item in enumerate(buffered):
        if _matches(
            item, trace_id=trace_id, module=module, work_id=work_id, status=status
        ):
            return buffered.pop(index)
    while True:
        outcome = await asyncio.wait_for(brain.next_outcome(), timeout)
        if _matches(
            outcome, trace_id=trace_id, module=module, work_id=work_id, status=status
        ):
            return outcome
        buffered.append(outcome)
