from __future__ import annotations

from datetime import datetime, timezone

from app.domain.drives import DriveState
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.conversation_resume_state import ConversationResumeState


def test_agent_life_service_delegates_conversation_resume_state() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    resume_state = ConversationResumeState()
    service = AgentLifeService(
        ActivityManager(),
        now=now,
        conversation_resume_state=resume_state,
    )
    service.update_drive(DriveState(curiosity=0.9, energy=0.9))

    service.end_conversation(reason="user_finished")
    event = service.plan_next_event(now=now)

    assert resume_state.explicit_end_reason == "user_finished"
    assert event is not None
    assert event.payload["resume_reason"] == "conversation_ended:user_finished"

    service.handle_event(event)

    assert resume_state.explicit_end_reason is None
    assert resume_state.observed_ongoing_activity_id is None
