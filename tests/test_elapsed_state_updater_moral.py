from datetime import datetime, timedelta, timezone

from app.runtime.agent_state import AgentState
from app.runtime.elapsed_state_updater import ElapsedStateUpdater


def test_elapsed_state_updater_returns_moral_toward_profile_baseline() -> None:
    initial_time = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    updater = ElapsedStateUpdater(initial_time=initial_time)
    state = AgentState().with_moral(
        AgentState().current_moral.adjusted(
            selfish_impulse=0.4,
            aggressive_impulse=0.4,
            guilt=0.4,
        )
    )

    result = updater.update(
        state,
        now=initial_time + timedelta(minutes=15),
    )

    assert result.moral_elapsed_seconds == 900.0
    assert result.after_moral.selfish_impulse < result.before_moral.selfish_impulse
    assert (
        result.after_moral.aggressive_impulse
        < result.before_moral.aggressive_impulse
    )
    assert result.after_moral.guilt < result.before_moral.guilt
    assert result.state.current_moral == result.after_moral
    assert result.moral_changed is True


def test_record_event_resets_moral_elapsed_time_baseline() -> None:
    initial_time = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    event_time = initial_time + timedelta(seconds=30)
    updater = ElapsedStateUpdater(initial_time=initial_time)
    updater.record_event(event_time)

    result = updater.update(
        AgentState(),
        now=initial_time + timedelta(seconds=60),
    )

    assert result.moral_elapsed_seconds == 30.0
    assert updater.last_moral_updated_at == initial_time + timedelta(seconds=60)
