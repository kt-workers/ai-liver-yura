from datetime import datetime, timezone

import pytest

from app.domain.desires import DesireState, DesireType, DesireValue
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.desire_state_updater import DesireStateUpdater


def test_user_input_increases_connection_curiosity_and_expression() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "今日は何を話す？"},
    )

    updated = updater.update_by_event(state, event)

    assert updated.connection.level == pytest.approx(0.51)
    assert updated.curiosity.level == pytest.approx(0.54)
    assert updated.expression.level == pytest.approx(0.42)
    assert updated.recognition.level == pytest.approx(0.31)
    assert updated.security == state.security


def test_silence_timeout_increases_unfulfilled_connection_and_expression() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT)

    updated = updater.update_by_event(state, event)

    assert updated.connection.level == pytest.approx(0.48)
    assert updated.connection.frustration == pytest.approx(0.015)
    assert updated.expression.level == pytest.approx(0.43)
    assert updated.expression.frustration == pytest.approx(0.015)


def test_trend_updated_increases_curiosity_only() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(event_type=AgentEventType.TREND_UPDATED)

    updated = updater.update_by_event(state, event)

    assert updated.curiosity.level == pytest.approx(0.58)
    assert updated.connection == state.connection
    assert updated.expression == state.expression


def test_speech_finished_satisfies_expression() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(event_type=AgentEventType.SPEECH_FINISHED)

    updated = updater.update_by_event(state, event)

    assert updated.expression.satisfaction == pytest.approx(0.10)
    assert updated.connection.satisfaction == pytest.approx(0.02)
    assert updated.achievement.satisfaction == pytest.approx(0.02)


def test_action_failed_increases_security_and_achievement_frustration() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(event_type=AgentEventType.ACTION_FAILED)

    updated = updater.update_by_event(state, event)

    assert updated.security.level == pytest.approx(0.39)
    assert updated.achievement.level == pytest.approx(0.40)
    assert updated.achievement.frustration == pytest.approx(0.08)


def test_unknown_event_preserves_state() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(event_type=AgentEventType.CAMERA_FRAME)

    assert updater.update_by_event(state, event) == state


def test_elapsed_time_returns_level_toward_baseline_and_decays_satisfaction() -> None:
    updater = DesireStateUpdater()
    state = DesireState().with_value(
        DesireType.EXPRESSION,
        DesireValue(
            level=0.80,
            baseline=0.40,
            satisfaction=0.40,
            frustration=0.20,
        ),
    )

    updated = updater.update_by_elapsed_time(state, elapsed_seconds=60.0)

    assert updated.expression.level == pytest.approx(0.784)
    assert updated.expression.satisfaction == pytest.approx(0.32)
    assert updated.expression.frustration == pytest.approx(0.17)


def test_elapsed_time_increases_frustration_when_shortage_is_large() -> None:
    updater = DesireStateUpdater()
    state = DesireState().with_value(
        DesireType.CONNECTION,
        DesireValue(
            level=0.90,
            baseline=0.45,
            satisfaction=0.0,
            frustration=0.0,
        ),
    )

    updated = updater.update_by_elapsed_time(state, elapsed_seconds=60.0)

    assert updated.connection.level == pytest.approx(0.882)
    assert updated.connection.frustration == pytest.approx(0.01128)


def test_negative_elapsed_time_preserves_state() -> None:
    updater = DesireStateUpdater()
    state = DesireState()

    assert updater.update_by_elapsed_time(state, elapsed_seconds=-60.0) == state


def test_update_by_timestamps_uses_elapsed_seconds() -> None:
    updater = DesireStateUpdater()
    state = DesireState().with_value(
        DesireType.CURIOSITY,
        DesireValue(level=0.90, baseline=0.50),
    )
    previous_time = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    current_time = datetime(2026, 8, 1, 12, 1, tzinfo=timezone.utc)

    updated = updater.update_by_timestamps(
        state,
        previous_time=previous_time,
        current_time=current_time,
    )

    assert updated.curiosity.level < state.curiosity.level
