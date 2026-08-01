import pytest

from app.domain.activities import Activity, ActivityResult, ActivityType
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_result_desire_event import (
    build_activity_result_desire_event,
)
from app.runtime.agent_life_service import AgentLifeService


def test_agent_life_service_applies_activity_result_desire_once() -> None:
    service = AgentLifeService(ActivityManager())
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="会話する",
    )
    result = ActivityResult(
        result_type="speech_output",
        summary="会話した",
        data={"output_status": "completed"},
        succeeded=True,
    )
    event = build_activity_result_desire_event(activity, result)

    first = service.handle_event(event)
    second = service.handle_event(event)

    assert first.current_desire.connection.satisfaction == pytest.approx(0.08)
    assert first.current_desire.expression.satisfaction == pytest.approx(0.04)
    assert second.current_desire == first.current_desire


def test_agent_life_service_records_failed_activity_frustration() -> None:
    service = AgentLifeService(ActivityManager())
    activity = Activity(
        activity_type=ActivityType.CURIOSITY_RESEARCH,
        goal="調査する",
    )
    result = ActivityResult(
        result_type="action_output",
        summary="調査に失敗した",
        data={"output_status": "failed"},
        succeeded=False,
    )

    state = service.handle_event(
        build_activity_result_desire_event(activity, result)
    )

    assert state.current_desire.achievement.frustration == pytest.approx(0.07)
    assert state.current_desire.curiosity.frustration == pytest.approx(0.04)
    assert state.active_activity is None
