from __future__ import annotations

import pytest

from app.domain.actions import ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.avatar_performance import (
    AvatarExpressionIntent,
    AvatarGazeIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
)
from app.domain.character_response import CharacterResponse, ReactionPlan, ReactionSegment
from app.runtime.avatar_performance_action_planner import AvatarPerformanceActionPlanner
from app.runtime.avatar_performance_planner import AvatarPerformancePlanner


class UnusedResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        raise AssertionError("このテストではLLMを呼び出しません。")


def test_avatar_performance_domain_validates_ranges() -> None:
    with pytest.raises(ValueError, match="intensity"):
        AvatarExpressionIntent("happy", 1.1)
    with pytest.raises(ValueError, match="duration_ms"):
        AvatarPerformanceSegment(
            expression=AvatarExpressionIntent("happy"),
            duration_ms=99,
        )
    with pytest.raises(ValueError, match="at least one segment"):
        AvatarPerformancePlan(
            performance_id="perf-001",
            source_activity_id="activity-001",
            output_unit_id="output-001",
            priority=100,
            segments=(),
        )


def test_avatar_performance_planner_preserves_reaction_intents() -> None:
    planner = AvatarPerformancePlanner(
        performance_id_factory=lambda: "perf-001"
    )
    reaction_plan = ReactionPlan(
        (
            ReactionSegment(
                speech="気になるね",
                expression="curious",
                gesture="head_tilt",
                pause_after_seconds=0.2,
                expression_intensity=0.7,
                gesture_intensity=0.4,
                gaze=AvatarGazeIntent(
                    target="viewer",
                    behavior="maintain",
                    intensity=0.8,
                ),
            ),
            ReactionSegment(
                speech="もう少し見てみよう",
                expression="soft_smile",
                expression_intensity=0.5,
            ),
        )
    )

    performance = planner.plan(
        reaction_plan,
        source_activity_id="activity-001",
        output_unit_id="output-001",
        priority=100,
    )

    assert performance.performance_id == "perf-001"
    assert performance.source_activity_id == "activity-001"
    assert performance.output_unit_id == "output-001"
    assert performance.priority == 100
    assert len(performance.segments) == 2
    assert performance.segments[0].expression.name == "curious"
    assert performance.segments[0].expression.intensity == 0.7
    assert performance.segments[0].gesture is not None
    assert performance.segments[0].gesture.name == "head_tilt"
    assert performance.segments[0].gesture.intensity == 0.4
    assert performance.segments[0].gaze is not None
    assert performance.segments[0].gaze.target == "viewer"
    assert performance.segments[0].duration_ms >= 600
    assert performance.segments[1].gesture is None


def test_avatar_performance_action_planner_attaches_plan_once() -> None:
    planner = AvatarPerformanceActionPlanner(
        UnusedResponseGenerator(),
        avatar_performance_planner=AvatarPerformancePlanner(
            performance_id_factory=lambda: "perf-001"
        ),
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="応答する",
        activity_id="activity-001",
    )
    response = CharacterResponse(
        speech="気になるね続けよう",
        reaction_plan=ReactionPlan(
            (
                ReactionSegment(
                    speech="気になるね",
                    expression="curious",
                    gesture="head_tilt",
                    expression_intensity=0.7,
                    gesture_intensity=0.4,
                    gaze=AvatarGazeIntent("viewer", intensity=0.8),
                ),
                ReactionSegment(
                    speech="続けよう",
                    expression="happy",
                ),
            )
        ),
    )

    actions = planner._reaction_action_plans(
        activity,
        response,
        fallback_speech=response.speech,
        output_unit_id="output-001",
        base_metadata={},
        skip_topic_memory=False,
    )

    expression_actions = [
        action
        for action in actions
        if action.action_type == ActionType.CHANGE_EXPRESSION
    ]
    move_actions = [
        action for action in actions if action.action_type == ActionType.MOVE
    ]

    assert len(expression_actions) == 2
    assert len(move_actions) == 1
    first_performance = expression_actions[0].metadata[
        "avatar_performance_plan"
    ]
    assert isinstance(first_performance, AvatarPerformancePlan)
    assert first_performance.performance_id == "perf-001"
    assert first_performance.priority == 100
    assert len(first_performance.segments) == 2
    assert "avatar_performance_plan" not in expression_actions[1].metadata
    assert all(
        action.metadata["avatar_performance_id"] == "perf-001"
        and action.metadata["avatar_performance_managed"] is True
        for action in [*expression_actions, *move_actions]
    )
