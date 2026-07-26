from datetime import datetime, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime import ActivityManager, AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_event_planner import AutonomousEventPlanResult


class RecordingAutonomousEventPlanner:
    def __init__(self, event: AgentEvent) -> None:
        self.event = event
        self.calls: list[tuple[AgentState, datetime]] = []
        self.continuation_provider_called = False
        self.topic_provider_called = False

    def plan(
        self,
        state: AgentState,
        *,
        now: datetime,
        awakening_completed_at: datetime | None,
        continuation_provider,
        autonomous_topic_provider,
    ) -> AutonomousEventPlanResult:
        del awakening_completed_at
        self.calls.append((state, now))
        continuation_provider()
        self.continuation_provider_called = True
        autonomous_topic_provider()
        self.topic_provider_called = True
        return AutonomousEventPlanResult(
            event=self.event,
            log_event="agent_life_service:plan_next_event:planned",
            details={
                "event_type": self.event.event_type.value,
                "reason": "recording_planner",
            },
        )


def test_agent_life_service_delegates_autonomous_event_planning() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    expected = AgentEvent(
        event_type=AgentEventType.CURIOSITY_PEAK,
        payload={"reason": "recording_planner"},
    )
    planner = RecordingAutonomousEventPlanner(expected)
    service = AgentLifeService(
        ActivityManager(),
        now=now,
        autonomous_event_planner=planner,  # type: ignore[arg-type]
    )

    actual = service.plan_next_event(now=now)

    assert actual is expected
    assert len(planner.calls) == 1
    assert planner.calls[0][0] == service.agent_state
    assert planner.calls[0][1] == now
    assert planner.continuation_provider_called is True
    assert planner.topic_provider_called is True
