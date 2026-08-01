import pytest

from app.domain.desires import DesireState
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.desire_state_updater import DesireStateUpdater


def test_activity_result_event_updates_satisfaction_without_changing_behavior() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={
            "activity_type": "conversation_with_user",
            "outcome": "completed",
        },
    )

    updated = updater.update_by_event(state, event)

    assert updated.connection.satisfaction == pytest.approx(0.08)
    assert updated.expression.satisfaction == pytest.approx(0.04)
    assert updated.connection.level == state.connection.level
    assert updated.curiosity == state.curiosity


def test_failed_activity_result_increases_frustration() -> None:
    updater = DesireStateUpdater()
    state = DesireState()
    event = AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={
            "activity_type": "curiosity_research",
            "outcome": "failed",
        },
    )

    updated = updater.update_by_event(state, event)

    assert updated.security.level == pytest.approx(0.38)
    assert updated.achievement.level == pytest.approx(0.39)
    assert updated.achievement.frustration == pytest.approx(0.07)
    assert updated.curiosity.level == pytest.approx(0.53)
    assert updated.curiosity.frustration == pytest.approx(0.04)
