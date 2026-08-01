from datetime import datetime, timedelta, timezone

from app.domain.desires import DesireState, DesireType, DesireValue
from app.runtime.agent_state import AgentState
from app.runtime.elapsed_state_updater import ElapsedStateUpdater


def test_elapsed_state_updater_updates_desire_with_drive_and_emotion() -> None:
    initial_time = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    updater = ElapsedStateUpdater(initial_time=initial_time)
    desire = DesireState().with_value(
        DesireType.CURIOSITY,
        DesireValue(
            level=0.9,
            baseline=0.5,
            satisfaction=0.2,
        ),
    )
    state = AgentState().with_desire(desire)

    result = updater.update(
        state,
        now=initial_time + timedelta(minutes=1),
    )

    assert result.desire_elapsed_seconds == 60.0
    assert result.before_desire == desire
    assert result.after_desire.curiosity.level < desire.curiosity.level
    assert (
        result.after_desire.curiosity.satisfaction
        < desire.curiosity.satisfaction
    )
    assert result.state.current_desire == result.after_desire
    assert result.state.current_drive == result.after_drive
    assert result.state.current_emotion == result.after_emotion
    assert result.desire_changed is True


def test_record_event_resets_desire_elapsed_time_baseline() -> None:
    initial_time = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    event_time = initial_time + timedelta(seconds=30)
    updater = ElapsedStateUpdater(initial_time=initial_time)
    updater.record_event(event_time)

    result = updater.update(
        AgentState(),
        now=initial_time + timedelta(seconds=60),
    )

    assert result.desire_elapsed_seconds == 30.0
    assert updater.last_desire_updated_at == initial_time + timedelta(seconds=60)


def test_elapsed_state_updater_does_not_rewind_desire_clock() -> None:
    initial_time = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    updater = ElapsedStateUpdater(initial_time=initial_time)

    result = updater.update(
        AgentState(),
        now=initial_time - timedelta(seconds=10),
    )

    assert result.desire_elapsed_seconds == -10.0
    assert result.after_desire == result.before_desire
    assert updater.last_desire_updated_at == initial_time
