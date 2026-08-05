from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.actions import ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.domain.character_response import CharacterResponse
from app.runtime.avatar_body_command_action_planner import (
    AvatarBodyCommandActionPlanner,
)
from app.runtime.body_spatial_command_resolver import BodySpatialCommandResolver
from app.runtime.core_command_body_controller import (
    CoreCommandBodyController,
    group_body_actions,
)

pytestmark = pytest.mark.unit


class UnusedResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        raise AssertionError("このテストではLLMを呼び出しません。")


def test_compound_direction_and_arm_command_are_both_preserved() -> None:
    activity = _activity(
        "左を見たまま右手を挙げて",
        target={"type": "avatar_body_action", "id": "right_hand_raise"},
        entities=(
            {"body_part": "右手", "action": "挙げる"},
            {"body_part": "左目線", "action": "維持"},
        ),
    )
    resolver = BodySpatialCommandResolver()

    attention = resolver.resolve(activity)

    assert resolver.resolve_body_actions(activity) == ("right_hand_raise",)
    assert attention is not None
    assert attention.target == "left"


def test_multiple_independent_body_parts_are_resolved_together() -> None:
    activity = _activity(
        "左手を下におろして右足を挙げて",
        target=None,
        entities=(
            {"body_part": "左手", "action": "下におろす"},
            {"body_part": "右足", "action": "挙げる"},
        ),
    )

    actions = BodySpatialCommandResolver().resolve_body_actions(activity)

    assert actions == ("left_hand_lower", "right_leg_raise")
    assert group_body_actions(actions) == (
        ("left_hand_lower", "right_leg_raise"),
    )


def test_explicit_jump_count_is_preserved_as_sequential_steps() -> None:
    activity = _activity(
        "2回ジャンプしてー",
        target={"type": "avatar_body_action", "id": "jump"},
        primary_intent="perform_two_jumps",
    )

    actions = BodySpatialCommandResolver().resolve_body_actions(activity)

    assert actions == ("jump", "jump")
    assert group_body_actions(actions) == (("jump",), ("jump",))


def test_repeat_request_reuses_previous_body_action_and_attention() -> None:
    planner = AvatarBodyCommandActionPlanner(UnusedResponseGenerator())
    first = _activity(
        "左を見たまま右手を挙げて",
        target={"type": "avatar_body_action", "id": "right_hand_raise"},
    )
    repeated = _activity(
        "もう一回やって",
        target=None,
        primary_intent="repeat_previous_action",
    )

    _body_request(planner, first)
    repeat_request = _body_request(planner, repeated)

    assert repeat_request.body_actions == ("right_hand_raise",)
    assert repeat_request.attention is not None
    assert repeat_request.attention.target == "left"


def test_core_controller_moves_leg_joint_while_independent_arm_command_runs() -> None:
    controller = CoreCommandBodyController(tick_hz=30.0, seed=7)
    controller.apply_body_commands(
        ("left_hand_lower", "right_leg_raise"),
        duration_ms=1200,
    )

    frame = None
    for sequence in range(18):
        frame = controller.tick(
            timestamp_ms=sequence * 33,
            dt_seconds=1.0 / 30.0,
        )

    assert frame is not None
    assert set(controller.active_body_commands) == {
        "left_hand_lower",
        "right_leg_raise",
    }
    right_upper_leg = next(
        joint for joint in frame.joints if joint.joint_id == "right_upper_leg"
    )
    assert abs(right_upper_leg.rotation.x) > 0.1


def test_stick_mock_reads_canonical_leg_joints() -> None:
    source = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-body-pose-lab"
        / "web"
        / "body-pose-skeleton.js"
    ).read_text(encoding="utf-8")

    assert "left_upper_leg" in source
    assert "right_upper_leg" in source
    assert "legRaiseFromFrame" in source


def _body_request(
    planner: AvatarBodyCommandActionPlanner,
    activity: Activity,
) -> SpeechCoupledBodyExpressionRequest:
    response = CharacterResponse(
        speech="了解だよ。",
        expression="smile",
    )
    plans = planner._reaction_action_plans(
        activity,
        response,
        fallback_speech=response.speech,
        output_unit_id=f"output-{activity.activity_id}",
        base_metadata={},
        skip_topic_memory=False,
    )
    expression_plan = next(
        plan for plan in plans if plan.action_type is ActionType.CHANGE_EXPRESSION
    )
    request = expression_plan.metadata["body_expression_request"]
    assert isinstance(request, SpeechCoupledBodyExpressionRequest)
    return request


def _activity(
    text: str,
    *,
    target: dict[str, str] | None,
    primary_intent: str = "アバター身体を操作する",
    entities: tuple[dict[str, object], ...] = (),
) -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="アバター身体命令に応答する",
        context={
            "constraints": {
                "_internal_directive": {
                    "structured_input_meaning": {
                        "input_speech_act": "command",
                        "primary_intent": primary_intent,
                        "expected_response": "action",
                        "target": target,
                        "entities": [dict(entity) for entity in entities],
                        "references": [],
                        "information_provided": [text],
                        "confidence": 0.96,
                    }
                }
            },
            "event_payload": {
                "text": text,
                "behavior_plan": {"speech_act": "command"},
            },
        },
    )
