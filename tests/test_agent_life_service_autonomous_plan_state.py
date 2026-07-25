from __future__ import annotations

from datetime import datetime, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.autonomous_plan_state import AutonomousPlanState


def test_agent_life_service_records_accepted_plan_in_injected_state() -> None:
    planned_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    plan_state = AutonomousPlanState(default_retry_backoff_seconds=7.0)
    service = AgentLifeService(
        ActivityManager(),
        autonomous_plan_state=plan_state,
    )
    event = AgentEvent(
        event_type=AgentEventType.CURIOSITY_PEAK,
        payload={"autonomous_planned_for": planned_at.isoformat()},
    )

    service.handle_event(event)

    assert plan_state.last_accepted_at == planned_at
    assert plan_state.last_rejected_at is None
    assert plan_state.reconsider_after_seconds == 7.0


def test_agent_life_service_records_rejected_plan_in_injected_state() -> None:
    rejected_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    plan_state = AutonomousPlanState()
    service = AgentLifeService(
        ActivityManager(),
        autonomous_plan_state=plan_state,
    )
    event = AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK)

    service.record_autonomous_plan_rejected(
        event,
        rejected_at=rejected_at,
        reconsider_after_seconds=12.0,
    )

    assert plan_state.last_rejected_at == rejected_at
    assert plan_state.reconsider_after_seconds == 12.0


def test_non_autonomous_rejection_does_not_change_injected_state() -> None:
    plan_state = AutonomousPlanState()
    service = AgentLifeService(
        ActivityManager(),
        autonomous_plan_state=plan_state,
    )

    service.record_autonomous_plan_rejected(
        AgentEvent(event_type=AgentEventType.USER_TEXT),
    )

    assert plan_state.last_rejected_at is None
