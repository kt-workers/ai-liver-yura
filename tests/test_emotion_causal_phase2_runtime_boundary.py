from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState


def test_normal_runtime_does_not_turn_silence_timeout_directly_into_desire() -> None:
    before = AgentState()

    result = AgentEventStateUpdater().update(
        before,
        AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT),
    )

    assert result.after_emotion == result.before_emotion
    assert result.after_desire == result.before_desire
    assert result.state.current_desire == before.current_desire
