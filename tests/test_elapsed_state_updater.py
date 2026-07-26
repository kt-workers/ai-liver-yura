from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType
from app.runtime.agent_state import AgentState
from app.runtime.elapsed_state_updater import ElapsedStateUpdater


def test_update_applies_drive_and_emotion_elapsed_changes() -> None:
    initial_time = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    updater = ElapsedStateUpdater(initial_time=initial_time)
    state = AgentState(
        current_drive=DriveState(
            curiosity=0.2,
            engagement=0.4,
            boredom=0.2,
            energy=0.8,
        ),
        current_emotion=EmotionState(
            mood=MoodType.EXCITED,
            arousal=0.9,
            valence=0.8,
            talkativeness=0.9,
        ),
    )

    result = updater.update(
        state,
        now=initial_time + timedelta(seconds=60),
    )

    assert result.drive_elapsed_seconds == 60.0
    assert result.emotion_elapsed_seconds == 60.0
    assert result.state.current_drive == result.after_drive
    assert result.state.current_emotion == result.after_emotion
    assert result.before_drive != result.after_drive
    assert result.before_emotion != result.after_emotion
    assert result.emotion_changed is True


def test_record_event_moves_only_emotion_reference_time_forward() -> None:
    initial_time = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    updater = ElapsedStateUpdater(initial_time=initial_time)
    event_time = initial_time + timedelta(seconds=30)

    updater.record_event(event_time)
    updater.record_event(initial_time)

    assert updater.last_drive_updated_at == initial_time
    assert updater.last_emotion_updated_at == event_time


def test_update_does_not_decay_emotion_for_older_time() -> None:
    initial_time = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    updater = ElapsedStateUpdater(initial_time=initial_time)
    state = AgentState(
        current_emotion=EmotionState(
            mood=MoodType.EXCITED,
            arousal=0.9,
            valence=0.8,
            talkativeness=0.9,
        )
    )

    result = updater.update(
        state,
        now=initial_time - timedelta(seconds=10),
    )

    assert result.emotion_elapsed_seconds == 0.0
    assert result.after_emotion == result.before_emotion
    assert updater.last_emotion_updated_at == initial_time
