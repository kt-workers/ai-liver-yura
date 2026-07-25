from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState


class RecordingAgentEventStateUpdater(AgentEventStateUpdater):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[AgentEvent] = []

    def update(self, state: AgentState, event: AgentEvent):
        self.events.append(event)
        return super().update(state, event)


def test_agent_life_service_delegates_event_state_update() -> None:
    updater = RecordingAgentEventStateUpdater()
    service = AgentLifeService(
        ActivityManager(),
        agent_event_state_updater=updater,
    )
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは", "source": "console"},
    )

    state = service.handle_event(event)

    assert updater.events == [event]
    assert state.current_situation.last_event_id == event.event_id
    assert state.current_situation.input_source == "console"
    assert state.last_user_input_at == event.occurred_at
    assert state.memory.episodic[-1].event_id == event.event_id
