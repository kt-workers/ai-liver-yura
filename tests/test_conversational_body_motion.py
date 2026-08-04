from __future__ import annotations

import pytest

from app.domain.actions import ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.body import BodyActivityContext, EmbodiedExpressionIntent
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.domain.character_response import CharacterResponse
from app.runtime.avatar_performance_action_planner import AvatarPerformanceActionPlanner
from app.runtime.conversational_body_expression_planner import (
    ConversationalBodyExpressionPlanner,
)

pytestmark = pytest.mark.unit


class UnusedResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        raise AssertionError("このテストではLLMを呼び出しません。")


def test_speech_coupled_request_normalizes_speech_act() -> None:
    request = SpeechCoupledBodyExpressionRequest(
        source_activity_id="activity-1",
        output_unit_id="output-1",
        expression=EmbodiedExpressionIntent(),
        speech_act=" Question ",
    )

    assert request.speech_act == "question"


def test_conversation_without_llm_motion_intent_gets_body_owned_speech_tracks() -> None:
    planner = AvatarPerformanceActionPlanner(UnusedResponseGenerator())
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問に応答する",
        activity_id="activity-1",
        context={
            "event_payload": {
                "behavior_plan": {
                    "speech_act": "question",
                }
            }
        },
    )
    response = CharacterResponse(
        speech="あなたはどう思いますか？",
        expression="smile",
    )

    actions = planner._reaction_action_plans(
        activity,
        response,
        fallback_speech=response.speech,
        output_unit_id="output-1",
        base_metadata={},
        skip_topic_memory=False,
    )
    expression_action = next(
        action for action in actions if action.action_type == ActionType.CHANGE_EXPRESSION
    )
    request = expression_action.metadata["body_expression_request"]
    context = expression_action.metadata["body_activity_context"]

    assert isinstance(request, SpeechCoupledBodyExpressionRequest)
    assert isinstance(context, BodyActivityContext)
    assert request.speech_act == "question"
    assert request.expression.approach > 0.0

    tracks = ConversationalBodyExpressionPlanner().compile(
        request,
        activity_context=context,
        segment_index=0,
        start_offset_ms=0,
        duration_ms=request.duration_hint_ms or 1600,
    )
    motion_names = {
        track.motion.name for track in tracks if track.motion is not None
    }

    assert "speech_cadence" in motion_names
    assert "speech_sway" in motion_names
    assert "question_tilt" in motion_names
    assert any(
        track.duration_ms == request.duration_hint_ms
        for track in tracks
        if track.motion is not None and track.motion.name == "speech_cadence"
    )


def test_statement_speech_moves_without_forcing_question_gesture() -> None:
    request = SpeechCoupledBodyExpressionRequest(
        source_activity_id="activity-1",
        output_unit_id="output-1",
        expression=EmbodiedExpressionIntent(
            attitude="calm",
            intensity=0.4,
            arousal=0.25,
        ),
        duration_hint_ms=4200,
        speech_act="statement",
    )
    context = BodyActivityContext(
        source_activity_id="activity-1",
        attention_target="conversation_partner",
        engagement=0.7,
        movement_energy=0.4,
    )

    tracks = ConversationalBodyExpressionPlanner().compile(
        request,
        activity_context=context,
        segment_index=0,
        start_offset_ms=0,
        duration_ms=4200,
    )
    motion_names = {
        track.motion.name for track in tracks if track.motion is not None
    }

    assert "speech_cadence" in motion_names
    assert "speech_sway" in motion_names
    assert "question_tilt" not in motion_names
    assert "small_nod" not in motion_names
