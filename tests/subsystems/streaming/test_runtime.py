from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.subsystems.streaming.contracts import (
    StreamingEffectState,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExecutionStatus,
    StreamingExternalObservation,
    StreamingExternalState,
    StreamingObservationSourceKind,
    StreamingOperation,
)
from app.subsystems.streaming.runtime import StreamingSubsystemRuntime

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def request() -> StreamingExecutionRequest:
    return StreamingExecutionRequest(
        "execution:1", "activity:1", "cap:stream", 1, StreamingOperation.START_STREAM, 2, "trace:1"
    )


class Provider:
    async def execute(self, value: StreamingExecutionRequest) -> StreamingExecutionReport:
        return StreamingExecutionReport(
            value.execution_id,
            value.operation,
            StreamingExecutionStatus.SUCCEEDED,
            StreamingEffectState.APPLIED,
            NOW,
            ("observation:1",),
            False,
        )


def test_provider_neutral_execution_keeps_effect_truth_separate() -> None:
    async def scenario() -> None:
        result = await StreamingSubsystemRuntime(Provider()).execute(request())
        assert result.status is StreamingExecutionStatus.SUCCEEDED
        assert result.effect_state is StreamingEffectState.APPLIED

    asyncio.run(scenario())


def test_stale_observation_and_comment_burst_are_bounded() -> None:
    runtime = StreamingSubsystemRuntime(Provider(), comment_limit=1)
    current = StreamingExternalObservation(
        "observation:2",
        StreamingExternalState.LIVE,
        StreamingObservationSourceKind.PROVIDER_OBSERVATION,
        "stream:1",
        NOW,
        1,
        2,
    )
    stale = StreamingExternalObservation(
        "observation:1",
        StreamingExternalState.READY,
        StreamingObservationSourceKind.PROVIDER_OBSERVATION,
        "stream:1",
        NOW,
        1,
        1,
    )
    assert runtime.accept_observation(current)
    assert not runtime.accept_observation(stale)
    runtime.ingest_comment_signal("signal:1")
    runtime.ingest_comment_signal("signal:2")
    assert runtime.drain_comment_signals() == ("signal:2",)
