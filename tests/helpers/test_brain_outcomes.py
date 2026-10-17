"""Brain結果の照合が他のtraceを破棄しないことの回帰試験。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import cast

import pytest

from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainWorkStatus,
)
from app.usecases.brain_integration_runtime import (
    BrainIntegrationRuntime,
    BrainIntegrationWorkOutcome,
)
from tests.helpers.brain_outcomes import (
    collect_work_outcomes,
    next_outcome_matching,
    wait_for_work_outcome,
)


class _Brain:
    def __init__(self, *outcomes: BrainIntegrationWorkOutcome) -> None:
        self.queue: asyncio.Queue[BrainIntegrationWorkOutcome] = asyncio.Queue()
        for outcome in outcomes:
            self.queue.put_nowait(outcome)

    async def next_outcome(self) -> BrainIntegrationWorkOutcome:
        return await self.queue.get()


def _outcome(
    work_id: str,
    trace_id: str,
    module: BrainIntegrationModule = BrainIntegrationModule.INPUT_MEANING,
    status: BrainWorkStatus = BrainWorkStatus.COMPLETED,
) -> BrainIntegrationWorkOutcome:
    return BrainIntegrationWorkOutcome(
        work_id, trace_id, module, BrainIntegrationLane.COGNITIVE_NORMAL,
        status, datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_out_of_order_modules_are_kept_for_next_match() -> None:
    first = _outcome("a", "one", BrainIntegrationModule.APPRAISAL)
    second = _outcome("b", "two", BrainIntegrationModule.EXECUTIVE)
    brain = cast(BrainIntegrationRuntime, _Brain(first, second))
    assert await next_outcome_matching(
        brain, trace_id="two", module=BrainIntegrationModule.EXECUTIVE
    ) is second
    assert await next_outcome_matching(
        brain, trace_id="one", module=BrainIntegrationModule.APPRAISAL
    ) is first


@pytest.mark.asyncio
async def test_status_and_id_filters_do_not_discard_other_results() -> None:
    first = _outcome("failed", "one", status=BrainWorkStatus.FAILED)
    second = _outcome("done", "two")
    brain = cast(BrainIntegrationRuntime, _Brain(first, second))
    assert await next_outcome_matching(
        brain, work_id="done", status=BrainWorkStatus.COMPLETED
    ) is second
    assert await next_outcome_matching(
        brain, work_id="failed", status=BrainWorkStatus.FAILED
    ) is first


@pytest.mark.asyncio
async def test_collection_keeps_unrelated_result_for_later_waiter() -> None:
    unrelated = _outcome("unrelated", "startup")
    second = _outcome("second", "user")
    first = _outcome("first", "user")
    brain = cast(BrainIntegrationRuntime, _Brain(unrelated, second, first))
    assert await collect_work_outcomes(brain, ("first", "second")) == (first, second)
    assert await wait_for_work_outcome(brain, "unrelated") is unrelated


@pytest.mark.asyncio
async def test_timeout_preserves_earlier_unmatched_result() -> None:
    existing = _outcome("existing", "initial")
    brain = cast(BrainIntegrationRuntime, _Brain(existing))
    with pytest.raises(asyncio.TimeoutError):
        await next_outcome_matching(brain, work_id="absent", timeout=0.01)
    assert await next_outcome_matching(brain, work_id="existing") is existing


@pytest.mark.asyncio
async def test_matching_requires_filter_and_valid_deadline() -> None:
    brain = cast(BrainIntegrationRuntime, _Brain())
    with pytest.raises(ValueError):
        await next_outcome_matching(brain)
    with pytest.raises(ValueError):
        await next_outcome_matching(brain, work_id="a", timeout=0)
