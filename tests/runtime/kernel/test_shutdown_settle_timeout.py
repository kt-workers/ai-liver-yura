import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    FakeRuntimeClock,
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeCoordinator,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkPriority,
)
from app.runtime.shutdown import (
    RuntimeShutdownError,
    RuntimeShutdownPolicy,
    RuntimeShutdownStage,
)

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_in_flight_settle_timeout_never_becomes_stopped_after_hard_cancel_cleanup() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        runtime = RuntimeCoordinator(
            FakeRuntimeClock(NOW),
            RuntimeSchedulerPolicy("test.scheduler", 1, 8),
            RuntimeShutdownPolicy("test.shutdown", 1, 0.0, 1.0, 1.0, 1.0),
        )

        async def handler(_work: RuntimeWorkItem[object], _token: object) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

        runtime.register_lane(
            RuntimeLanePolicy(
                "lane",
                1,
                QueuePolicy.REJECT_NEW,
                1,
                0.0,
                LaneErrorPolicy.ISOLATE,
            ),
            handler,
        )
        await runtime.start()
        runtime.submit(
            RuntimeWorkItem(
                "work",
                "lane",
                None,
                WorkPriority.NORMAL,
                RevisionVector(1),
                NOW,
                interruptible=False,
            )
        )
        await started.wait()

        with pytest.raises(RuntimeShutdownError) as captured:
            await runtime.stop()

        assert runtime.state.value == "stopping"
        assert any(
            failure.stage is RuntimeShutdownStage.IN_FLIGHT_SETTLE
            for failure in captured.value.failures
        )
        assert not any(
            failure.stage is RuntimeShutdownStage.OWNED_TASK_JOIN
            for failure in captured.value.failures
        )
        assert runtime.diagnostics().owned_task_count == 0

        with pytest.raises(RuntimeShutdownError):
            await runtime.stop()

    asyncio.run(scenario())
