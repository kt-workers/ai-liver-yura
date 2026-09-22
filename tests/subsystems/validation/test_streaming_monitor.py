"""本番の配信観測と集中コメント処理を同じ実行基盤で確認する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.subsystems.streaming.contracts import (
    StreamingCommentEvent,
    StreamingCommentModerationState,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExternalObservation,
    StreamingExternalState,
    StreamingObservationSourceKind,
)
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.streaming import StreamingLabCase, streaming_target
from app.subsystems.validation.streaming_monitor import (
    StreamingMonitorFrame,
    StreamingMonitorSettings,
)
from tests.subsystems.streaming import test_runtime as product
from tests.subsystems.validation.json_values import array_at, value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case(settings: StreamingMonitorSettings, *, execute: bool = False) -> StreamingLabCase:
    item = StreamingLabCase(
        FIXTURE,
        product.capability(),
        (product.request(),) if execute else (),
        product.NOW,
        settings,
    )
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


def comment(index: int, channel: str = "channel") -> StreamingCommentEvent:
    return StreamingCommentEvent(f"comment:{index}", channel, "配信へのコメントです", product.NOW)


@pytest.mark.asyncio
async def test_burst_uses_product_bounded_queue_and_coalesced_signals() -> None:
    item = case(
        StreamingMonitorSettings(
            (StreamingMonitorFrame(tuple(comment(i) for i in range(100))),), 0.001, 4
        )
    )
    runner = ValidationRunner(
        (streaming_target((item,), product.Provider(), PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(replace(spec(), target_module="streaming"), item.fixture)
    assert result.status is RunStatus.COMPLETED
    value = result.stage_results[0].typed_outputs
    assert value_at(value, "monitor", "dropped_comments") == 96
    signals = array_at(value, "monitor", "samples", 0, "signals")
    assert len(signals) == 1
    assert value_at(signals[0], "count") == 4
    assert value_at(signals[0], "representative_event_id") == "comment:96"
    assert value_at(value, "lifecycle_after_shutdown") == "stopped"
    assert value_at(value, "pending_streaming_tasks") == runner.pending_count == 0


@pytest.mark.asyncio
async def test_provider_and_user_observations_keep_distinct_reconciled_histories() -> None:
    user = StreamingExternalObservation(
        "user",
        StreamingExternalState.LIVE,
        StreamingObservationSourceKind.USER_REPORT,
        "stream",
        product.NOW,
        0.8,
        None,
    )
    provider = StreamingExternalObservation(
        "provider",
        StreamingExternalState.READY,
        StreamingObservationSourceKind.PROVIDER_OBSERVATION,
        "stream",
        product.NOW + timedelta(seconds=1),
        1.0,
        1,
    )
    later = replace(
        provider,
        observation_id="later",
        state=StreamingExternalState.LIVE,
        observed_at=product.NOW + timedelta(seconds=2),
    )
    stale = replace(later, observation_id="stale", provider_generation=0)
    item = case(
        StreamingMonitorSettings(
            tuple(
                StreamingMonitorFrame(observations=(value,))
                for value in (user, provider, later, stale)
            ),
            0.001,
            4,
        )
    )
    runner = ValidationRunner(
        (streaming_target((item,), product.Provider(), PROVENANCE, "1"),),
        replace(POLICY, max_intervals=24),
    )
    result = await runner.run(replace(spec(), target_module="streaming"), item.fixture)
    assert result.status is RunStatus.COMPLETED
    value = result.stage_results[0].typed_outputs
    samples = array_at(value, "monitor", "samples")
    assert [value_at(row, "accepted_observations", 0) for row in samples] == [
        True,
        True,
        True,
        False,
    ]
    histories = array_at(value, "monitor", "histories")
    assert value_at(histories[0], "source_kind") == "user_report"
    assert value_at(histories[0], "observations", 0, "reconciliation") == "contradicted"
    assert len(array_at(histories[1], "observations")) == 2
    assert value_at(histories[1], "observations", 1, "state") == "live"
    assert value_at(value, "reports") == ()


class Moderator:
    def __init__(self) -> None:
        self.started, self.release, self.stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def moderate(self, value: StreamingCommentEvent) -> StreamingCommentModerationState:
        self.started.set()
        try:
            await self.release.wait()
            return StreamingCommentModerationState.ACCEPTED
        finally:
            self.stopped.set()


@pytest.mark.asyncio
async def test_slow_moderation_does_not_delay_stream_execution() -> None:
    moderator, executed = Moderator(), asyncio.Event()

    class Provider(product.Provider):
        async def execute(self, value: StreamingExecutionRequest) -> StreamingExecutionReport:
            await moderator.started.wait()
            result = await super().execute(value)
            executed.set()
            return result

    item = case(
        StreamingMonitorSettings((StreamingMonitorFrame((comment(1),)),), 0.03, 4), execute=True
    )
    target = streaming_target((item,), Provider(), PROVENANCE, "1", moderator=moderator)
    runner = ValidationRunner((target,), replace(POLICY, max_intervals=24))
    task = asyncio.create_task(runner.run(replace(spec(), target_module="streaming"), item.fixture))
    await asyncio.wait_for(executed.wait(), 0.5)
    assert not moderator.release.is_set() and not task.done()
    moderator.release.set()
    result = await task
    assert result.status is RunStatus.COMPLETED
    value = result.stage_results[0].typed_outputs
    assert value_at(value, "reports", 0, "effect_state") == "applied"
    assert value_at(value, "monitor", "samples", 0, "signals", 0, "count") == 1
    moderation = next(row for row in result.timeline if row.stage == "streaming.moderation")
    execution = next(row for row in result.timeline if row.stage == "streaming.provider")
    assert moderation.overlaps(execution)
    assert execution.completed_ns < moderation.completed_ns
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_pending_moderation_is_collected_at_window_end_or_cancel(cancel: bool) -> None:
    moderator = Moderator()
    item = case(StreamingMonitorSettings((StreamingMonitorFrame((comment(1),)),), 0.02, 4))
    runner = ValidationRunner(
        (streaming_target((item,), product.Provider(), PROVENANCE, "1", moderator=moderator),),
        POLICY,
    )
    task = asyncio.create_task(runner.run(replace(spec(), target_module="streaming"), item.fixture))
    await asyncio.wait_for(moderator.started.wait(), 0.5)
    if cancel:
        await runner.cancel(spec().run_id)
    result = await task
    assert result.status is (RunStatus.CANCELLED if cancel else RunStatus.COMPLETED)
    assert moderator.stopped.is_set() and runner.pending_count == 0
    if not cancel:
        value = result.stage_results[0].typed_outputs
        assert value_at(value, "monitor", "pending_at_window_end") == 1
        assert value_at(value, "monitor", "samples", 0, "signals") == ()
        assert value_at(value, "pending_streaming_tasks") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_rejected_or_failed_moderation_does_not_publish_comment_signal(failed: bool) -> None:
    class RejectingModerator:
        async def moderate(self, value: StreamingCommentEvent) -> StreamingCommentModerationState:
            if failed:
                raise RuntimeError("模擬審査先を利用できません")
            return StreamingCommentModerationState.REJECTED

    item = case(StreamingMonitorSettings((StreamingMonitorFrame((comment(1),)),), 0.001, 4))
    runner = ValidationRunner(
        (
            streaming_target(
                (item,), product.Provider(), PROVENANCE, "1", moderator=RejectingModerator()
            ),
        ),
        POLICY,
    )
    result = await runner.run(replace(spec(), target_module="streaming"), item.fixture)
    assert result.status is RunStatus.COMPLETED
    value = result.stage_results[0].typed_outputs
    assert value_at(value, "monitor", "samples", 0, "signals") == ()
    assert value_at(value, "monitor", "dropped_comments") == int(failed)
    assert value_at(value, "pending_streaming_tasks") == runner.pending_count == 0
