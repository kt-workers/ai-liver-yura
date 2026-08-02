from datetime import datetime, timedelta, timezone

from app.domain.drives import DriveState
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState
from app.runtime.drive_state_updater import DriveStateUpdater


def _drag(
    occurred_at: datetime,
    phase: str,
    *,
    gesture_id: str = "drag-1",
) -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.USER_INTERACTION,
        occurred_at=occurred_at,
        payload={
            "source": "inner_state_visualizer",
            "stimulus_kind": "drag",
            "gesture_id": gesture_id,
            "gesture_phase": phase,
            "continuous_contact": True,
            "contact_duration_ms": max(
                0.0,
                (occurred_at - datetime(2026, 8, 2, tzinfo=timezone.utc)).total_seconds()
                * 1000.0,
            ),
            "contact_sample_interval_ms": 140.0,
        },
    )


def test_drive_updates_again_after_one_second_while_dragging() -> None:
    started_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    updater = DriveStateUpdater()
    initial = DriveState(curiosity=0.4, engagement=0.4, boredom=0.5, energy=0.8)

    after_start = updater.update_by_event(initial, _drag(started_at, "start"))
    within_segment = updater.update_by_event(
        after_start,
        _drag(started_at + timedelta(seconds=0.5), "update"),
    )
    after_next_segment = updater.update_by_event(
        within_segment,
        _drag(started_at + timedelta(seconds=1.05), "update"),
    )

    assert within_segment == after_start
    assert after_next_segment.curiosity > within_segment.curiosity
    assert after_next_segment.engagement > within_segment.engagement
    assert after_next_segment.energy < within_segment.energy


def test_state_history_is_recorded_once_per_contact_segment() -> None:
    started_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    updater = AgentEventStateUpdater()
    initial = AgentState()

    after_start = updater.update(initial, _drag(started_at, "start")).state
    history_after_start = len(after_start.memory.emotion_history)

    after_early_update = updater.update(
        after_start,
        _drag(started_at + timedelta(seconds=0.4), "update"),
    ).state
    history_after_early_update = len(after_early_update.memory.emotion_history)

    after_next_segment = updater.update(
        after_early_update,
        _drag(started_at + timedelta(seconds=1.1), "update"),
    ).state
    history_after_next_segment = len(after_next_segment.memory.emotion_history)

    assert history_after_start == 1
    assert history_after_early_update == history_after_start
    assert history_after_next_segment == history_after_start + 1
    assert after_early_update.current_drive == after_start.current_drive
    assert after_early_update.current_emotion == after_start.current_emotion
    assert after_next_segment.current_drive != after_early_update.current_drive
