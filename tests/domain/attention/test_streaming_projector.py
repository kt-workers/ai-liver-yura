"""実際の配信集約から注意受付までと、任意実装への非依存を検証する。"""

import asyncio
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from app.domain.attention import (
    AttentionPriority,
    AttentionSchedulingPolicy,
    AttentionSourceKind,
    AttentionTurnStore,
    ExecutiveTriggerEligibility,
)
from app.domain.attention.coordinator import AttentionCoordinator
from app.domain.contracts.streaming import StreamingCommentSignal
from app.subsystems.streaming.contracts import (
    StreamingCapabilityView,
    StreamingCommentEvent,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingOperation,
)
from app.subsystems.streaming.contracts import (
    StreamingCommentSignal as LegacyStreamingCommentSignal,
)
from app.subsystems.streaming.runtime import StreamingSubsystemRuntime
from app.usecases.attention import AttentionProjectionEnvelope, StreamingAttentionProjector

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


class UnusedProvider:
    async def execute(self, request: StreamingExecutionRequest) -> StreamingExecutionReport:
        raise AssertionError("コメントの集約だけで配信操作を実行してはいけません")


def test_burst_is_aggregated_before_attention_and_keeps_background_priority() -> None:
    async def scenario() -> None:
        runtime = StreamingSubsystemRuntime(
            UnusedProvider(),
            StreamingCapabilityView("cap:stream", 1, tuple(StreamingOperation), True, 1),
            comment_limit=4,
            clock=lambda: NOW,
        )
        try:
            for index in range(100):
                await runtime.ingest_comment(
                    StreamingCommentEvent(f"event:{index}", "channel:1", "コメント", NOW)
                )
            await asyncio.sleep(0)
            facts = runtime.drain_comment_signals()
            assert len(facts) == 1
            fact = facts[0]
            assert fact.count == 4
            assert fact.representative_event_id == "event:96"
            assert runtime.dropped_comment_count == 96
            assert runtime.drain_comment_signals() == ()
            signal = StreamingAttentionProjector().project(AttentionProjectionEnvelope(fact, 3))
            store = AttentionTurnStore(AttentionSchedulingPolicy.production())
            queued: list[ExecutiveTriggerEligibility] = []
            claim = AttentionCoordinator(store, store, queued.append).handle(signal, 1, NOW)
            assert claim is not None and queued == [claim]
            assert claim.source_ref == fact.signal_id
            assert claim.source_context_revision == 3
            assert claim.reason_kind is AttentionSourceKind.STREAMING
            assert claim.priority is AttentionPriority.BACKGROUND
            assert claim.source_revision is None
            assert not signal.trusted_direct_user
            assert not claim.interruption_allowed
        finally:
            await runtime.shutdown()
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_duplicate_offer_is_rejected_and_streaming_budget_remains_authoritative() -> None:
    store = AttentionTurnStore(AttentionSchedulingPolicy.production())
    projector = StreamingAttentionProjector()
    first = projector.project(
        AttentionProjectionEnvelope(
            StreamingCommentSignal("signal:1", "channel:1", "event:1", 1, NOW), 1
        )
    )
    first_state = store.offer(first)
    with pytest.raises(ValueError, match="既知source"):
        store.offer(first)
    assert store.snapshot() == first_state
    second = projector.project(
        AttentionProjectionEnvelope(
            StreamingCommentSignal("signal:2", "channel:1", "event:2", 100, NOW), 1
        )
    )
    second_state = store.offer(second)
    assert {source.source_ref for source in second_state.sources} == {"signal:1", "signal:2"}
    third = projector.project(
        AttentionProjectionEnvelope(
            StreamingCommentSignal("signal:3", "channel:2", "event:3", 1000, NOW), 1
        )
    )
    assert store.offer(third) == second_state
    assert all(
        source.effective_priority is AttentionPriority.BACKGROUND for source in second_state.sources
    )


def test_original_public_import_keeps_the_same_contract_identity() -> None:
    assert LegacyStreamingCommentSignal is StreamingCommentSignal


def test_attention_import_and_projection_do_not_require_streaming_implementation() -> None:
    script = """
import importlib.abc
import sys
from datetime import datetime, timezone
class RejectSubsystems(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.subsystems" or fullname.startswith("app.subsystems."):
            raise AssertionError("任意の実装を読み込もうとしました: " + fullname)
sys.meta_path.insert(0, RejectSubsystems())
from app.domain.contracts.streaming import StreamingCommentSignal
from app.usecases.attention import AttentionProjectionEnvelope, StreamingAttentionProjector
fact = StreamingCommentSignal("signal:1", "channel:1", "event:1", 1, datetime.now(timezone.utc))
signal = StreamingAttentionProjector().project(AttentionProjectionEnvelope(fact, 1))
assert signal.source_ref == "signal:1"
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
