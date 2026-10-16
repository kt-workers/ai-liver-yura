"""Runtime kernelの時計・取消契約を検証する。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.kernel import CancellationRecord, CancellationRegistry, FakeRuntimeClock

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def test_fake_clock_advances_deterministically() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        await clock.sleep(5)
        assert (clock.now() - NOW).total_seconds() == 5
        assert clock.sleeps == [5]

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_cancellation_is_idempotent_and_completed_work_is_not_rewritten() -> None:
    registry = CancellationRegistry()
    token = registry.register("work-1")
    waiter = asyncio.create_task(token.wait())
    try:
        assert registry.cancel("work-1", "superseded", NOW)
        record = await asyncio.wait_for(waiter, 1.0)
        assert record is token.record
        assert not registry.cancel("work-1", "again", NOW + timedelta(seconds=1))
        assert token.record == CancellationRecord("work-1", "superseded", NOW)
        registry.complete("work-1")
        assert registry.active_work_ids() == ()
        assert not registry.cancel("work-1", "late", NOW)
        with pytest.raises(ValueError):
            registry.register("work-1")
    finally:
        if not waiter.done():
            waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
