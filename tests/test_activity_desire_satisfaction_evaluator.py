import pytest

from app.domain.activities import ActivityType
from app.domain.desires import DesireType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_desire_satisfaction_evaluator import (
    ActivityDesireSatisfactionEvaluator,
)


def _event(activity_type: ActivityType, outcome: str) -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={
            "activity_type": activity_type.value,
            "outcome": outcome,
        },
    )


def test_completed_conversation_satisfies_connection_and_expression() -> None:
    evaluator = ActivityDesireSatisfactionEvaluator()

    result = evaluator.evaluate(
        _event(ActivityType.CONVERSATION_WITH_USER, "completed")
    )

    assert result[DesireType.CONNECTION] == pytest.approx((0.0, 0.08, 0.0))
    assert result[DesireType.EXPRESSION] == pytest.approx((0.0, 0.04, 0.0))
    assert DesireType.ACHIEVEMENT not in result


def test_failed_exploration_increases_curiosity_and_achievement_frustration() -> None:
    evaluator = ActivityDesireSatisfactionEvaluator()

    result = evaluator.evaluate(
        _event(ActivityType.CURIOSITY_RESEARCH, "failed")
    )

    assert result[DesireType.SECURITY] == pytest.approx((0.03, 0.0, 0.0))
    assert result[DesireType.ACHIEVEMENT] == pytest.approx((0.04, 0.0, 0.07))
    assert result[DesireType.CURIOSITY] == pytest.approx((0.03, 0.0, 0.04))


def test_partial_social_activity_keeps_half_satisfaction_and_small_frustration() -> None:
    evaluator = ActivityDesireSatisfactionEvaluator()

    result = evaluator.evaluate(
        _event(ActivityType.CONVERSATION_WITH_USER, "partial")
    )

    assert result[DesireType.CONNECTION] == pytest.approx((0.0, 0.04, 0.01))
    assert result[DesireType.EXPRESSION] == pytest.approx((0.0, 0.02, 0.0))
    assert result[DesireType.ACHIEVEMENT] == pytest.approx((0.01, 0.0, 0.02))


def test_canceled_activity_is_weaker_than_failed_activity() -> None:
    evaluator = ActivityDesireSatisfactionEvaluator()

    canceled = evaluator.evaluate(
        _event(ActivityType.TOPIC_EXPLORATION, "canceled")
    )
    failed = evaluator.evaluate(
        _event(ActivityType.TOPIC_EXPLORATION, "failed")
    )

    assert canceled[DesireType.ACHIEVEMENT][2] < failed[DesireType.ACHIEVEMENT][2]
    assert canceled[DesireType.CURIOSITY][2] < failed[DesireType.CURIOSITY][2]


def test_invalid_activity_result_payload_produces_no_adjustment() -> None:
    evaluator = ActivityDesireSatisfactionEvaluator()
    event = AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={"activity_type": "unknown", "outcome": "completed"},
    )

    assert evaluator.evaluate(event) == {}
