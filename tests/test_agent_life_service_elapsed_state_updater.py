from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.elapsed_state_updater import (
    ElapsedStateUpdateResult,
    ElapsedStateUpdater,
)


class RecordingElapsedStateUpdater(ElapsedStateUpdater):
    def __init__(self, *, initial_time: datetime) -> None:
        super().__init__(initial_time=initial_time)
        self.updated_at: list[datetime] = []
        self.event_times: list[datetime] = []

    def update(
        self,
        state: AgentState,
        *,
        now: datetime,
    ) -> ElapsedStateUpdateResult:
        self.updated_at.append(now)
        return super().update(state, now=now)

    def record_event(self, occurred_at: datetime) -> None:
        self.event_times.append(occurred_at)
        super().record_event(occurred_at)


def test_agent_life_service_delegates_elapsed_and_event_time_updates() -> None:
    initial_time = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    plan_time = initial_time + timedelta(seconds=30)
    event_time = initial_time + timedelta(seconds=45)
    updater = RecordingElapsedStateUpdater(initial_time=initial_time)
    service = AgentLifeService(
        ActivityManager(),
        now=initial_time,
        elapsed_state_updater=updater,
    )

    service.plan_next_event(now=plan_time)
    service.handle_event(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "こんにちは"},
            occurred_at=event_time,
        )
    )

    assert updater.updated_at == [plan_time]
    assert updater.event_times == [event_time]
    assert updater.last_emotion_updated_at == event_time
