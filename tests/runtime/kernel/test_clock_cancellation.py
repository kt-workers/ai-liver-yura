import asyncio
from datetime import datetime, timezone

from app.runtime.kernel import CancellationRegistry, FakeRuntimeClock

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def test_fake_clock_advances_deterministically() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        await clock.sleep(5)
        assert (clock.now() - NOW).total_seconds() == 5
        assert clock.sleeps == [5]

    asyncio.run(scenario())


def test_cancellation_is_idempotent_and_completed_work_is_not_rewritten() -> None:
    registry = CancellationRegistry()
    token = registry.register("work-1")
    assert registry.cancel("work-1", "superseded", NOW)
    assert token.cancelled
    assert not registry.cancel("work-1", "again", NOW)
    registry.complete("work-1")
    assert not registry.cancel("work-1", "late", NOW)
