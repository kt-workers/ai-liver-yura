from __future__ import annotations

import json

import pytest

from app.adapters.prompt import CharacterPromptBuilder
from app.domain.actions import ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarExpressionIntent,
    AvatarGazeIntent,
    AvatarMotionIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
    AvatarPerformanceTrack,
    AvatarTrackChannel,
)
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ReactionPlan,
    ReactionSegment,
    ResponseContext,
)
from app.runtime.avatar_performance_action_planner import AvatarPerformanceActionPlanner
from app.runtime.avatar_performance_planner import AvatarPerformancePlanner
from app.runtime.character_response_pipeline import CharacterLlmService


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
    with pytest.raises(ValueError, match="track or segment"):
        AvatarPerformancePlan(
            performance_id="perf-001",
            source_activity_id="activity-001",
            output_unit_id="output-001",
            priority=100,
        )
    with pytest.raises(ValueError, match="exactly one"):
        AvatarPerformanceTrack(
            track_id="invalid",
            channel=AvatarTrackChannel.HEAD,
            start_offset_ms=0,
            duration_ms=1000,
            expression=AvatarExpressionIntent("happy"),
            motion=AvatarMotionIntent("head_shake"),
        )


def test_avatar_performance_tracks_can_overlap_and_hold_independently() -> None:
    performance = AvatarPerformancePlan(
        performance_id="perf-001",
        source_activity_id="activity-001",
        output_unit_id="output-001",
        priority=100,
        tracks=(
            AvatarPerformanceTrack(
                track_id="attention",
                channel=AvatarTrackChannel.ATTENTION,
                start_offset_ms=0,
                duration_ms=3000,
                hold=True,
                attention=AvatarGazeIntent("viewer"),
            ),
            AvatarPerformanceTrack(
                track_id="head-shake",
                channel=AvatarTrackChannel.HEAD,
                start_offset_ms=200,
                duration_ms=1200,
                blend_mode=AvatarBlendMode.ADDITIVE,
                motion=AvatarMotionIntent(
                    "head_shake",
                    intensity=0.8,
                    repetitions=3,
                ),
            ),
            AvatarPerformanceTrack(
                track_id="lean-back",
                channel=AvatarTrackChannel.TORSO,
                start_offset_ms=120,
                duration_ms=1800,
                blend_mode=AvatarBlendMode.ADDITIVE,
                motion=AvatarMotionIntent("lean_back", intensity=0.6),
            ),
        ),
    )

    assert performance.duration_ms == 3000
    assert performance.tracks[0].hold is True
    assert performance.tracks[1].start_offset_ms == 200
    assert performance.tracks[2].start_offset_ms < performance.tracks[1].end_offset_ms


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
    assert performance.segments[0].gesture is not None
    assert performance.segments[0].gaze is not None

    assert len(performance.tracks) == 4
    expression, attention, head, next_expression = performance.tracks
    assert expression.channel == AvatarTrackChannel.EXPRESSION
    assert attention.channel == AvatarTrackChannel.ATTENTION
    assert head.channel == AvatarTrackChannel.HEAD
    assert head.blend_mode == AvatarBlendMode.ADDITIVE
    assert expression.start_offset_ms == attention.start_offset_ms == head.start_offset_ms
    assert next_expression.start_offset_ms == performance.segments[0].duration_ms
    assert expression.hold is True
    assert head.hold is False


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
    assert first_performance.tracks
    assert "avatar_performance_plan" not in expression_actions[1].metadata
    assert all(
        action.metadata["avatar_performance_id"] == "perf-001"
        and action.metadata["avatar_performance_managed"] is True
        for action in [*expression_actions, *move_actions]
    )


def test_character_llm_parser_accepts_avatar_performance_intents() -> None:
    response = CharacterLlmService.parse(
        json.dumps(
            {
                "speech": "気になるね",
                "expression": "curious",
                "gesture": "head_tilt",
                "voice_intent": {"style": "bright"},
                "pause_after_seconds": 0.0,
                "reaction_segments": [
                    {
                        "speech": "気になるね",
                        "expression": "curious",
                        "expression_intensity": 0.7,
                        "gesture": "head_tilt",
                        "gesture_intensity": 0.4,
                        "gaze": {
                            "target": "viewer",
                            "behavior": "maintain",
                            "intensity": 0.8,
                        },
                        "voice_intent": {"style": "bright"},
                        "pause_after_seconds": 0.0,
                    }
                ],
                "claims": [],
            },
            ensure_ascii=False,
        )
    )

    assert response is not None
    segment = response.effective_reaction_plan().segments[0]
    assert segment.expression_intensity == 0.7
    assert segment.gesture_intensity == 0.4
    assert segment.gaze is not None
    assert segment.gaze.target == "viewer"
    assert segment.gaze.eye_follow == 1.0
    assert segment.gaze.head_follow == 0.55


def test_character_prompt_limits_avatar_fields_to_high_level_intents() -> None:
    context = ResponseContext(
        user_input="気になる？",
        activity_type=ActivityType.CONVERSATION_WITH_USER.value,
        operation=None,
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(),
        forbidden_claims=(),
        activity_goal="応答する",
    )

    prompt = CharacterPromptBuilder().build(
        context,
        character_profile=None,
        correction=None,
    )

    assert "expression_intensity" in prompt
    assert "gesture_intensity" in prompt
    assert "gaze" in prompt
    assert "performance_id" in prompt
    assert "Live2D Parameter" in prompt
