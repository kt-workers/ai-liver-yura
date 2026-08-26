from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.subsystems.streaming.contracts import (
    StreamingCapabilityView,
    StreamingCommentEvent,
    StreamingCommentModerationState,
    StreamingEffectState,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExecutionStatus,
    StreamingExternalObservation,
    StreamingExternalState,
    StreamingObservationReconciliation,
    StreamingObservationSourceKind,
    StreamingOperation,
    StreamingSubsystemLifecycle,
)
from app.subsystems.streaming.runtime import StreamingSubsystemRuntime

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def capability(
    *,
    revision: int = 1,
    generation: int = 1,
    available: bool = True,
    operations: tuple[StreamingOperation, ...] = tuple(StreamingOperation),
) -> StreamingCapabilityView:
    return StreamingCapabilityView("cap:stream", revision, operations, available, generation)


def request(
    operation: StreamingOperation = StreamingOperation.START_STREAM,
    *,
    revision: int = 1,
    deadline_at: datetime | None = None,
) -> StreamingExecutionRequest:
    return StreamingExecutionRequest(
        "execution:1",
        "activity:1",
        "cap:stream",
        revision,
        operation,
        2,
        "trace:1",
        deadline_at=deadline_at,
    )


class Provider:
    def __init__(self, *, delay: bool = False, unavailable: bool = False) -> None:
        self.calls: list[StreamingExecutionRequest] = []
        self.delay = delay
        self.unavailable = unavailable

    async def execute(self, value: StreamingExecutionRequest) -> StreamingExecutionReport:
        self.calls.append(value)
        if self.delay:
            await asyncio.Event().wait()
        if self.unavailable:
            raise RuntimeError("provider unavailable")
        return StreamingExecutionReport(
            value.execution_id,
            value.operation,
            StreamingExecutionStatus.SUCCEEDED,
            StreamingEffectState.APPLIED,
            NOW,
            ("observation:1",),
            False,
            started_at=NOW,
        )


@pytest.mark.parametrize("operation", tuple(StreamingOperation))
def test_provider_neutral_prepare_start_end_and_status_execution(
    operation: StreamingOperation,
) -> None:
    async def scenario() -> None:
        provider = Provider()
        result = await StreamingSubsystemRuntime(provider, capability(), clock=lambda: NOW).execute(
            request(operation)
        )
        assert result.status is StreamingExecutionStatus.SUCCEEDED
        assert result.effect_state is StreamingEffectState.APPLIED
        assert provider.calls == [request(operation)]

    asyncio.run(scenario())


def test_stale_or_unavailable_capability_rejects_before_provider_invocation() -> None:
    async def scenario() -> None:
        provider = Provider()
        stale = await StreamingSubsystemRuntime(provider, capability(), clock=lambda: NOW).execute(
            request(revision=0)
        )
        unavailable = await StreamingSubsystemRuntime(
            provider, capability(available=False), clock=lambda: NOW
        ).execute(request())
        assert stale.effect_state is StreamingEffectState.NOT_APPLIED
        assert unavailable.status is StreamingExecutionStatus.PROVIDER_UNAVAILABLE
        assert provider.calls == []

    asyncio.run(scenario())


def test_deadline_before_execution_is_known_no_effect_and_timeout_after_start_is_ambiguous(
) -> None:
    async def scenario() -> None:
        provider = Provider()
        before = await StreamingSubsystemRuntime(provider, capability(), clock=lambda: NOW).execute(
            request(deadline_at=NOW)
        )
        delayed = Provider(delay=True)
        after = await StreamingSubsystemRuntime(delayed, capability(), clock=lambda: NOW).execute(
            request(deadline_at=NOW + timedelta(milliseconds=1))
        )
        assert before.status is StreamingExecutionStatus.FAILED
        assert before.effect_state is StreamingEffectState.NOT_APPLIED
        assert after.status is StreamingExecutionStatus.TIMED_OUT
        assert after.effect_state is StreamingEffectState.AMBIGUOUS

    asyncio.run(scenario())


def test_provider_unavailable_and_post_execution_generation_drift_fail_closed() -> None:
    async def scenario() -> None:
        unavailable = await StreamingSubsystemRuntime(
            Provider(unavailable=True), capability(), clock=lambda: NOW
        ).execute(request())
        assert unavailable.status is StreamingExecutionStatus.PROVIDER_UNAVAILABLE
        assert unavailable.effect_state is StreamingEffectState.UNKNOWN

        runtime: StreamingSubsystemRuntime

        class DriftingProvider(Provider):
            async def execute(self, value: StreamingExecutionRequest) -> StreamingExecutionReport:
                runtime.update_capability(capability(generation=2))
                return await super().execute(value)

        runtime = StreamingSubsystemRuntime(DriftingProvider(), capability(), clock=lambda: NOW)
        result = await runtime.execute(request())
        assert result.status is StreamingExecutionStatus.UNKNOWN_EFFECT
        assert result.effect_state is StreamingEffectState.AMBIGUOUS

    asyncio.run(scenario())


def test_shutdown_cancels_and_awaits_inflight_provider_execution() -> None:
    class BlockingProvider(Provider):
        def __init__(self) -> None:
            super().__init__(delay=True)
            self.started = asyncio.Event()

        async def execute(self, value: StreamingExecutionRequest) -> StreamingExecutionReport:
            self.calls.append(value)
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled provider execution must not complete")

    async def scenario() -> None:
        provider = BlockingProvider()
        runtime = StreamingSubsystemRuntime(provider, capability(), clock=lambda: NOW)
        execution = asyncio.create_task(runtime.execute(request()))
        await provider.started.wait()
        await runtime.shutdown()
        result = await execution
        assert result.status is StreamingExecutionStatus.CANCELLED
        assert result.effect_state is StreamingEffectState.AMBIGUOUS
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "effect"),
    (
        (StreamingExecutionStatus.SUCCEEDED, StreamingEffectState.NOT_APPLIED),
        (StreamingExecutionStatus.FAILED, StreamingEffectState.APPLIED),
        (StreamingExecutionStatus.TIMED_OUT, StreamingEffectState.NOT_APPLIED),
    ),
)
def test_execution_report_rejects_contradictory_effect_truth(
    status: StreamingExecutionStatus, effect: StreamingEffectState
) -> None:
    with pytest.raises(ValueError, match="effect truth"):
        StreamingExecutionReport(
            "execution:bad", StreamingOperation.START_STREAM, status, effect, NOW, (), False
        )


def test_execution_report_rejects_inverted_timestamps() -> None:
    with pytest.raises(ValueError, match="time"):
        StreamingExecutionReport(
            "execution:bad",
            StreamingOperation.START_STREAM,
            StreamingExecutionStatus.SUCCEEDED,
            StreamingEffectState.APPLIED,
            NOW,
            (),
            False,
            started_at=NOW + timedelta(seconds=1),
        )


def test_provider_observation_and_user_report_keep_separate_provenance_and_reconcile() -> None:
    runtime = StreamingSubsystemRuntime(Provider(), capability(), clock=lambda: NOW)
    user = StreamingExternalObservation(
        "observation:user",
        StreamingExternalState.LIVE,
        StreamingObservationSourceKind.USER_REPORT,
        "stream:1",
        NOW,
        0.4,
        None,
    )
    provider = StreamingExternalObservation(
        "observation:provider",
        StreamingExternalState.LIVE,
        StreamingObservationSourceKind.PROVIDER_OBSERVATION,
        "stream:1",
        NOW,
        1,
        2,
    )
    assert runtime.accept_observation(user)
    assert runtime.accept_observation(provider)
    user_history = runtime.observation_history(
        StreamingObservationSourceKind.USER_REPORT, "stream:1"
    )
    provider_history = runtime.observation_history(
        StreamingObservationSourceKind.PROVIDER_OBSERVATION, "stream:1"
    )
    assert len(user_history) == len(provider_history) == 1
    assert user_history[0].reconciliation is StreamingObservationReconciliation.CONFIRMED
    assert provider_history[0].source_kind is StreamingObservationSourceKind.PROVIDER_OBSERVATION


def test_stale_provider_observation_is_rejected_but_user_needs_no_provider_generation() -> None:
    runtime = StreamingSubsystemRuntime(Provider(), capability(), clock=lambda: NOW)
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
    assert runtime.accept_observation(
        StreamingExternalObservation(
            "observation:user",
            StreamingExternalState.READY,
            StreamingObservationSourceKind.USER_REPORT,
            "stream:1",
            NOW,
            0.5,
            None,
        )
    )


def test_old_same_generation_provider_observation_cannot_reconcile_newer_user_report() -> None:
    runtime = StreamingSubsystemRuntime(Provider(), capability(), clock=lambda: NOW)
    user = StreamingExternalObservation(
        "observation:user-newer",
        StreamingExternalState.LIVE,
        StreamingObservationSourceKind.USER_REPORT,
        "stream:1",
        NOW + timedelta(minutes=2),
        0.5,
        None,
    )
    older = StreamingExternalObservation(
        "observation:provider-older",
        StreamingExternalState.READY,
        StreamingObservationSourceKind.PROVIDER_OBSERVATION,
        "stream:1",
        NOW + timedelta(minutes=1),
        1,
        3,
    )
    newer = StreamingExternalObservation(
        "observation:provider-newer",
        StreamingExternalState.LIVE,
        StreamingObservationSourceKind.PROVIDER_OBSERVATION,
        "stream:1",
        NOW + timedelta(minutes=3),
        1,
        3,
    )
    delayed_older = StreamingExternalObservation(
        "observation:provider-delayed-older",
        StreamingExternalState.READY,
        StreamingObservationSourceKind.PROVIDER_OBSERVATION,
        "stream:1",
        NOW + timedelta(minutes=2),
        1,
        3,
    )

    assert runtime.accept_observation(user)
    assert runtime.accept_observation(older)
    assert runtime.observation_history(
        StreamingObservationSourceKind.USER_REPORT, "stream:1"
    )[0].reconciliation is StreamingObservationReconciliation.UNRECONCILED
    assert runtime.accept_observation(newer)
    assert not runtime.accept_observation(delayed_older)
    assert runtime.observation_history(
        StreamingObservationSourceKind.USER_REPORT, "stream:1"
    )[0].reconciliation is StreamingObservationReconciliation.CONFIRMED


def comment(event_id: str) -> StreamingCommentEvent:
    return StreamingCommentEvent(event_id, "channel:1", "こんにちは\u0000", NOW, "author:1")


def test_comment_burst_is_bounded_and_normalized_to_representative_signals() -> None:
    async def scenario() -> None:
        runtime = StreamingSubsystemRuntime(
            Provider(), capability(), comment_limit=1, clock=lambda: NOW
        )
        await runtime.ingest_comment(comment("comment:1"))
        await runtime.ingest_comment(comment("comment:2"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        signals = runtime.drain_comment_signals()
        assert len(signals) <= 1
        assert runtime.dropped_comment_count >= 1
        assert all(signal.source_channel_ref == "channel:1" for signal in signals)
        await runtime.shutdown()
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_accepted_comments_are_aggregated_as_one_representative_signal() -> None:
    async def scenario() -> None:
        runtime = StreamingSubsystemRuntime(
            Provider(), capability(), comment_limit=4, clock=lambda: NOW
        )
        await runtime.ingest_comment(comment("comment:1"))
        await runtime.ingest_comment(comment("comment:2"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        signals = runtime.drain_comment_signals()
        assert len(signals) == 1
        assert signals[0].count == 2
        await runtime.shutdown()

    asyncio.run(scenario())


def test_slow_moderation_does_not_block_comment_ingestion_or_execution() -> None:
    class SlowModerator:
        def __init__(self) -> None:
            self.gate = asyncio.Event()

        async def moderate(self, value: StreamingCommentEvent) -> StreamingCommentModerationState:
            await self.gate.wait()
            return StreamingCommentModerationState.ACCEPTED

    async def scenario() -> None:
        moderator = SlowModerator()
        runtime = StreamingSubsystemRuntime(
            Provider(), capability(), moderator=moderator, clock=lambda: NOW
        )
        await runtime.ingest_comment(comment("comment:slow"))
        result = await runtime.execute(request())
        assert result.status is StreamingExecutionStatus.SUCCEEDED
        moderator.gate.set()
        await asyncio.sleep(0)
        await runtime.shutdown()
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_reconnect_requires_a_fresh_capability_snapshot_before_execution_resumes() -> None:
    class ReconnectingProvider(Provider):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def reconnect(self) -> bool:
            self.attempts += 1
            return self.attempts == 2

    async def scenario() -> None:
        provider = ReconnectingProvider()
        runtime = StreamingSubsystemRuntime(
            provider,
            capability(available=False),
            reconnect_delay_s=0.001,
            clock=lambda: NOW,
        )
        absent = await runtime.execute(request())
        assert absent.status is StreamingExecutionStatus.PROVIDER_UNAVAILABLE
        assert runtime.start_reconnect()
        await asyncio.sleep(0.005)
        assert runtime.lifecycle is StreamingSubsystemLifecycle.DEGRADED
        still_unavailable = await runtime.execute(request())
        assert still_unavailable.status is StreamingExecutionStatus.PROVIDER_UNAVAILABLE
        runtime.update_capability(capability(generation=2))
        resumed = await runtime.execute(request())
        lifecycle = StreamingSubsystemLifecycle(runtime.lifecycle.value)
        assert lifecycle is StreamingSubsystemLifecycle.AVAILABLE
        assert resumed.status is StreamingExecutionStatus.SUCCEEDED
        await runtime.shutdown()
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())
