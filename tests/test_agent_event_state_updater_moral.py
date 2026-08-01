from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState


def test_event_state_updater_updates_moral_with_other_agent_state() -> None:
    updater = AgentEventStateUpdater()
    state = AgentState()
    event = AgentEvent(event_type=AgentEventType.ACTION_FAILED)

    result = updater.update(state, event)

    assert result.before_moral == state.current_moral
    assert result.after_moral.guilt > state.current_moral.guilt
    assert result.state.current_moral == result.after_moral
    assert result.state.current_desire == result.after_desire
    assert result.state.current_emotion == result.after_emotion


def test_user_input_activates_empathy_without_changing_profile() -> None:
    updater = AgentEventStateUpdater()
    state = AgentState()
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "話を聞いて"},
    )

    result = updater.update(state, event)

    assert result.after_moral.empathy_activation > state.current_moral.empathy_activation
    assert result.state.moral_profile == state.moral_profile
