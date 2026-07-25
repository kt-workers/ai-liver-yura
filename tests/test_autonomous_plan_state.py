from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.autonomous_plan_state import AutonomousPlanState


def test_accept_uses_planned_time_and_clears_rejection() -> None:
    planned_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    state = AutonomousPlanState(
        default_retry_backoff_seconds=2.0,
        last_rejected_at=planned_at - timedelta(seconds=1),
        reconsider_after_seconds=30.0,
    )
    event = AgentEvent(
        event_type=AgentEventType.CURIOSITY_PEAK,
        payload={"autonomous_planned_for": planned_at.isoformat()},
    )

    accepted_at = state.accept(event)

    assert accepted_at == planned_at
    assert state.last_accepted_at == planned_at
    assert state.last_rejected_at is None
    assert state.reconsider_after_seconds == 2.0


def test_accept_falls_back_to_event_time_for_invalid_timestamp() -> None:
    occurred_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    event = AgentEvent(
        event_type=AgentEventType.CURIOSITY_PEAK,
        payload={"autonomous_planned_for": "not-a-date"},
        occurred_at=occurred_at,
    )

    accepted_at = AutonomousPlanState().accept(event)

    assert accepted_at == occurred_at


def test_reject_clamps_explicit_reconsider_delay() -> None:
    rejected_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    event = AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK)
    state = AutonomousPlanState()

    assert state.reject(
        event,
        rejected_at=rejected_at,
        reconsider_after_seconds=1.0,
    )
    assert state.last_rejected_at == rejected_at
    assert state.reconsider_after_seconds == 5.0

    state.reject(event, rejected_at=rejected_at, reconsider_after_seconds=999.0)
    assert state.reconsider_after_seconds == 300.0


def test_retry_and_talk_interval_checks_use_recorded_times() -> None:
    accepted_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    rejected_at = accepted_at + timedelta(seconds=10)
    state = AutonomousPlanState(default_retry_backoff_seconds=20.0)
    state.accept(
        AgentEvent(
            event_type=AgentEventType.CURIOSITY_PEAK,
            payload={"autonomous_planned_for": accepted_at.isoformat()},
        )
    )
    state.reject(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK),
        rejected_at=rejected_at,
    )

    assert state.is_retry_backoff_active(rejected_at + timedelta(seconds=19))
    assert not state.is_retry_backoff_active(rejected_at + timedelta(seconds=20))
    assert state.is_talk_interval_active(accepted_at + timedelta(seconds=29), 30.0)
    assert not state.is_talk_interval_active(accepted_at + timedelta(seconds=30), 30.0)


def test_non_autonomous_event_does_not_change_plan_state() -> None:
    state = AutonomousPlanState()
    event = AgentEvent(event_type=AgentEventType.USER_TEXT)

    assert state.accept(event) is None
    assert not state.reject(event)
    assert state.last_accepted_at is None
    assert state.last_rejected_at is None
