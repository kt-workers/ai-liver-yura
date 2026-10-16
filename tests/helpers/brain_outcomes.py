"""Brainの非直列終端をtrace/module/work単位で取得する試験ヘルパー。"""

from __future__ import annotations

import asyncio

from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.usecases.brain_integration_runtime import (
    BrainIntegrationRuntime,
    BrainIntegrationWorkOutcome,
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
    """到着順を仮定せず、指定した識別情報に一致する終端だけを返す。"""
    while True:
        outcome = await asyncio.wait_for(brain.next_outcome(), timeout)
        if trace_id is not None and outcome.trace_id != trace_id:
            continue
        if module is not None and outcome.module is not module:
            continue
        if work_id is not None and outcome.work_id != work_id:
            continue
        if status is not None and outcome.status is not status:
            continue
        return outcome
