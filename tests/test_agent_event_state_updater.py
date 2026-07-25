from __future__ import annotations

from datetime import datetime, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState


def test_update_records_event_drive_emotion_memory_and_situation() -> None:
    occurred_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは", "source": "console"},
        occurred_at=occurred_at,
    )

    result = AgentEventStateUpdater().update(AgentState(), event)

    assert result.state.last_user_input_at == occurred_at
    assert result.state.current_situation.last_event_id == event.event_id
    assert result.state.current_situation.input_source == "console"
    assert result.state.current_drive == result.after_drive
    assert result.state.current_emotion == result.after_emotion
    assert result.before_drive != result.after_drive
    assert result.before_emotion != result.after_emotion
    assert result.state.memory.episodic[-1].event_id == event.event_id
    assert result.state.memory.emotion_history[-1].source_event_id == event.event_id


def test_update_ignores_blank_input_source() -> None:
    event = AgentEvent(
        event_type=AgentEventType.ACTION_FAILED,
        payload={"source": "   "},
    )

    result = AgentEventStateUpdater().update(AgentState(), event)

    assert result.input_source is None
    assert result.state.current_situation.input_source is None


def test_update_marks_speech_lifecycle() -> None:
    started_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 7, 26, 12, 0, 5, tzinfo=timezone.utc)
    updater = AgentEventStateUpdater()

    started = updater.update(
        AgentState(),
        AgentEvent(
            event_type=AgentEventType.SPEECH_STARTED,
            occurred_at=started_at,
        ),
    ).state
    finished = updater.update(
        started,
        AgentEvent(
            event_type=AgentEventType.SPEECH_FINISHED,
            occurred_at=finished_at,
        ),
    ).state

    assert started.last_speech_started_at == started_at
    assert finished.last_speech_finished_at == finished_at
