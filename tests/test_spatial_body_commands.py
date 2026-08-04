from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.actions import ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.domain.character_response import CharacterResponse
from app.runtime.avatar_performance_action_planner import AvatarPerformanceActionPlanner
from app.runtime.body_spatial_command_resolver import BodySpatialCommandResolver
from app.runtime.cognitive_direction_parsers import InputMeaningJsonParser

pytestmark = pytest.mark.unit


class UnusedResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        raise AssertionError("このテストではLLMを呼び出しません。")


def _meaning_payload(
    *,
    speech_act: str = "command",
    expected_response: str = "action",
    primary_intent: str,
    information: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "input_speech_act": speech_act,
            "primary_intent": primary_intent,
            "expected_response": expected_response,
            "target": None,
            "entities": [],
            "references": [],
            "information_provided": information or [],
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "conversation_phase_signal": "continue",
            "confidence": 0.95,
            "reason": "spatial command",
        },
        ensure_ascii=False,
    )


def test_input_meaning_normalizes_diagonal_gaze_command() -> None:
    meaning = InputMeaningJsonParser().parse(
        _meaning_payload(
            primary_intent="右上を見るよう指示している",
            information=["右上見てみて"],
        ),
        source_text="右上見てみて",
    )

    assert meaning is not None
    assert meaning.target is not None
    assert meaning.target.target_type == "gaze_direction"
    assert meaning.target.target_id == "up_right"


def test_input_meaning_normalizes_body_orientation_command() -> None:
    meaning = InputMeaningJsonParser().parse(
        _meaning_payload(
            primary_intent="左を向く動作を指示している",
            information=["左を向いて"],
        ),
        source_text="左を向いて",
    )

    assert meaning is not None
    assert meaning.target is not None
    assert meaning.target.target_type == "orientation_direction"
    assert meaning.target.target_id == "left"


def test_non_action_direction_reference_is_not_converted_to_body_command() -> None:
    meaning = InputMeaningJsonParser().parse(
        _meaning_payload(
            speech_act="statement",
            expected_response="acknowledgement",
            primary_intent="左側の画面について説明している",
            information=["左側は暗いね"],
        ),
        source_text="左側は暗いね",
    )

    assert meaning is not None
    assert meaning.target is None


def test_orientation_command_uses_more_body_follow_than_gaze_command() -> None:
    resolver = BodySpatialCommandResolver()
    gaze_activity = _activity_with_target("gaze_direction", "right")
    turn_activity = _activity_with_target("orientation_direction", "left")

    gaze = resolver.resolve(gaze_activity)
    turn = resolver.resolve(turn_activity)

    assert gaze is not None
    assert turn is not None
    assert gaze.target == "right"
    assert turn.target == "left"
    assert gaze.body_follow < turn.body_follow
    assert turn.head_follow == 1.0


def test_character_response_without_attention_still_turns_body() -> None:
    planner = AvatarPerformanceActionPlanner(UnusedResponseGenerator())
    activity = _activity_with_target("orientation_direction", "left")
    response = CharacterResponse(
        speech="うん、左を向いたよ。",
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

    assert isinstance(request, SpeechCoupledBodyExpressionRequest)
    assert request.attention is not None
    assert request.attention.target == "left"
    assert request.attention.body_follow == pytest.approx(0.78)


def test_stick_model_supports_diagonal_attention_and_visible_yaw() -> None:
    source = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
        / "body-runtime-motions.js"
    ).read_text(encoding="utf-8")

    assert "up_right" in source
    assert "down_left" in source
    assert "resolveAttentionTarget = function" in source
    assert "drawFace = function" in source
    assert "yaw * 22" in source


def _activity_with_target(target_type: str, target_id: str) -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="方向指示に応答する",
        activity_id="activity-1",
        context={
            "constraints": {
                "_internal_directive": {
                    "structured_input_meaning": {
                        "input_speech_act": "command",
                        "primary_intent": "方向を変える",
                        "expected_response": "action",
                        "target": {"type": target_type, "id": target_id},
                        "confidence": 0.95,
                    }
                }
            },
            "event_payload": {
                "behavior_plan": {
                    "speech_act": "command",
                }
            },
        },
    )
