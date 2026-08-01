from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState


def test_event_state_updater_updates_desire_with_other_agent_state() -> None:
    updater = AgentEventStateUpdater()
    state = AgentState()
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "新しい話をしよう"},
    )

    result = updater.update(state, event)

    assert result.before_desire == state.current_desire
    assert result.after_desire.connection.level > state.current_desire.connection.level
    assert result.after_desire.curiosity.level > state.current_desire.curiosity.level
    assert result.state.current_desire == result.after_desire
    assert result.state.current_drive == result.after_drive
    assert result.state.current_emotion == result.after_emotion


def test_event_state_updater_keeps_desire_observational_for_unmapped_event() -> None:
    updater = AgentEventStateUpdater()
    state = AgentState()
    event = AgentEvent(event_type=AgentEventType.CAMERA_FRAME)

    result = updater.update(state, event)

    assert result.after_desire == state.current_desire
    assert result.state.current_desire == state.current_desire
