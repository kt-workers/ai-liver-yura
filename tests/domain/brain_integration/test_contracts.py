from datetime import datetime, timedelta, timezone

import pytest

from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationTerminalOutcome,
    BrainIntegrationTrace,
    BrainRevisionEvent,
    BrainWorkEnvelope,
    BrainWorkInterval,
    BrainWorkPriority,
    BrainWorkStatus,
)

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _interval(
    *,
    work_id: str = "work:meaning:1",
    status: BrainWorkStatus = BrainWorkStatus.RUNNING,
    completed_at: datetime | None = None,
) -> BrainWorkInterval:
    return BrainWorkInterval(
        work_id,
        BrainIntegrationModule.INPUT_MEANING,
        BrainIntegrationLane.FOREGROUND_INTERACTION,
        status,
        NOW,
        NOW + timedelta(seconds=1),
        completed_at,
        3,
        4,
        5,
    )


def test_envelope_carries_correlation_and_owner_native_revisions_without_authority() -> None:
    envelope = BrainWorkEnvelope(
        "trace:1",
        "trigger:1",
        ("event:1",),
        3,
        4,
        5,
        BrainWorkPriority.DIRECT_USER,
        NOW,
    )

    assert envelope.source_event_ids == ("event:1",)
    assert envelope.goal_revision == 4
    assert envelope.attention_revision == 5


def test_interval_requires_a_terminal_timestamp_without_imposing_a_global_lock() -> None:
    completed_at = NOW + timedelta(seconds=2)
    interval = _interval(status=BrainWorkStatus.COMPLETED, completed_at=completed_at)

    assert interval.completed_at == completed_at

    with pytest.raises(ValueError, match="完了時刻"):
        _interval(status=BrainWorkStatus.CANCELLED)


def test_trace_keeps_distinct_module_work_and_revision_observation() -> None:
    trace = BrainIntegrationTrace(
        "trace:1",
        "trigger:1",
        ("event:1",),
        (_interval(status=BrainWorkStatus.COMPLETED, completed_at=NOW + timedelta(seconds=2)),),
        (
            BrainRevisionEvent(
                "revision-event:1",
                BrainIntegrationModule.ATTENTION,
                5,
                NOW + timedelta(seconds=3),
            ),
        ),
        decision_ids=("decision:1",),
        speech_candidate_ids=("speech:1",),
        terminal_outcome=BrainIntegrationTerminalOutcome.COMPLETED,
    )

    assert trace.decision_ids == ("decision:1",)
    assert trace.revision_events[0].owner is BrainIntegrationModule.ATTENTION


def test_trace_rejects_terminal_outcome_while_unrelated_work_is_still_running() -> None:
    with pytest.raises(ValueError, match="未終了"):
        BrainIntegrationTrace(
            "trace:1",
            "trigger:1",
            (),
            (_interval(),),
            (),
            terminal_outcome=BrainIntegrationTerminalOutcome.COMPLETED,
        )


def test_trace_rejects_duplicate_work_identity() -> None:
    completed_at = NOW + timedelta(seconds=2)
    with pytest.raises(ValueError, match="work_id"):
        BrainIntegrationTrace(
            "trace:1",
            "trigger:1",
            (),
            (
                _interval(status=BrainWorkStatus.COMPLETED, completed_at=completed_at),
                _interval(status=BrainWorkStatus.COMPLETED, completed_at=completed_at),
            ),
            (),
        )
