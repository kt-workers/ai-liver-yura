from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.actions import ActionType
from app.domain.activities import Activity, ActivityType
from app.domain.avatar_performance import AvatarTrackChannel
from app.domain.body import BodyActivityContext, EmbodiedExpressionIntent
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.domain.character import CharacterExistenceProfile
from app.domain.character_response import CharacterResponse
from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.runtime.avatar_aware_internal_directive_normalizer import (
    AvatarAwareInternalDirectiveCandidateNormalizer,
)
from app.runtime.avatar_body_command_action_planner import (
    AvatarBodyCommandActionPlanner,
)
from app.runtime.cognitive_direction_parsers import InputMeaningJsonParser
from app.runtime.conversational_body_expression_planner import (
    ConversationalBodyExpressionPlanner,
)
from app.runtime.living_body_runtime import LivingBodyRuntime

pytestmark = pytest.mark.unit


class UnusedResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        raise AssertionError("このテストではLLMを呼び出しません。")


def _meaning_json(text: str) -> str:
    return json.dumps(
        {
            "input_speech_act": "command",
            "primary_intent": "アバター身体を操作する",
            "expected_response": "action",
            "target": None,
            "entities": [],
            "references": [],
            "information_provided": [text],
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "conversation_phase_signal": "continue",
            "confidence": 0.96,
            "reason": "明示的な身体操作命令",
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    ("text", "expected_action"),
    [
        ("右手を挙げて", "right_hand_raise"),
        ("左手を上げて", "left_hand_raise"),
        ("両手を挙げて", "both_hands_raise"),
        ("眼を閉じて", "eyes_close"),
        ("目を開けて", "eyes_open"),
        ("口を開けて", "mouth_open"),
        ("口を閉じて", "mouth_close"),
        ("顔をぐるっと回して", "head_circle"),
        ("お辞儀して", "bow"),
        ("ジャンプして", "jump"),
        ("体を左右に揺らして", "body_sway"),
    ],
)
def test_input_meaning_normalizes_avatar_body_commands(
    text: str,
    expected_action: str,
) -> None:
    meaning = InputMeaningJsonParser().parse(
        _meaning_json(text),
        source_text=text,
    )

    assert meaning is not None
    assert meaning.target == InputTarget("avatar_body_action", expected_action)


def test_non_action_body_reference_is_not_converted_to_command() -> None:
    payload = json.loads(_meaning_json("右手が見えるね"))
    payload["input_speech_act"] = "statement"
    payload["expected_response"] = "acknowledgement"

    meaning = InputMeaningJsonParser().parse(
        json.dumps(payload, ensure_ascii=False),
        source_text="右手が見えるね",
    )

    assert meaning is not None
    assert meaning.target is None


def test_avatar_internal_directive_removes_false_physical_denial() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.COMMAND,
        primary_intent="raise_avatar_right_hand",
        expected_response=ExpectedResponse.ACTION,
        target=InputTarget("avatar_body_action", "right_hand_raise"),
        confidence=0.98,
    )
    candidate = InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal="物理的な身体がないので動かせないと説明する",
        activity_intent=None,
        initiative_level=0.6,
        question_budget=1,
        new_direction_budget=1,
        self_disclosure_level=0.1,
        content_requirements=(
            "物理的な身体を持たないため右手を上げられないと説明する",
        ),
        forbidden_claims=("物理的動作ができると述べる",),
    )

    normalized = AvatarAwareInternalDirectiveCandidateNormalizer().normalize(
        meaning,
        candidate,
        {},
    )

    assert normalized.response_mode is ResponseMode.REACT
    assert normalized.question_budget == 0
    assert normalized.new_direction_budget == 0
    assert any("アバター身体" in item for item in normalized.content_requirements)
    assert any("動かせない" in item for item in normalized.forbidden_claims)
    assert not any(
        "右手を上げられない" in item
        for item in normalized.content_requirements
    )


def test_existence_profile_distinguishes_real_and_avatar_bodies() -> None:
    profile = CharacterExistenceProfile()
    policies = profile.behavior_policies()

    assert any("現実世界" in item and "物理的な身体を持たない" in item for item in policies)
    assert any("アバター身体" in item and "動かせる" in item for item in policies)
    assert any("カメラ" in item and "マイク" in item for item in policies)
    assert any("Body Subsystem" in item and "実行" in item for item in policies)


def test_action_planner_attaches_body_command_without_character_gesture() -> None:
    planner = AvatarBodyCommandActionPlanner(UnusedResponseGenerator())
    activity = _activity_with_target("avatar_body_action", "right_hand_raise")
    response = CharacterResponse(
        speech="うん、右手を上げるね。",
        expression="smile",
    )

    plans = planner._reaction_action_plans(
        activity,
        response,
        fallback_speech=response.speech,
        output_unit_id="output-1",
        base_metadata={},
        skip_topic_memory=False,
    )
    expression_plan = next(
        plan for plan in plans if plan.action_type is ActionType.CHANGE_EXPRESSION
    )
    request = expression_plan.metadata["body_expression_request"]

    assert isinstance(request, SpeechCoupledBodyExpressionRequest)
    assert request.body_actions == ("right_hand_raise",)
    assert not any(plan.action_type is ActionType.MOVE for plan in plans)


@pytest.mark.parametrize(
    ("body_action", "channel", "axis", "target"),
    [
        ("right_hand_raise", AvatarTrackChannel.RIGHT_ARM, "right_arm_raise", 1.0),
        ("left_hand_raise", AvatarTrackChannel.LEFT_ARM, "left_arm_raise", 1.0),
        ("eyes_close", AvatarTrackChannel.FACE, "eye_closure", 1.0),
        ("eyes_open", AvatarTrackChannel.FACE, "eye_closure", 0.0),
        ("mouth_open", AvatarTrackChannel.FACE, "mouth_open", 1.0),
        ("mouth_close", AvatarTrackChannel.FACE, "mouth_open", 0.0),
    ],
)
def test_state_command_compiles_to_continuous_pose_target(
    body_action: str,
    channel: AvatarTrackChannel,
    axis: str,
    target: float,
) -> None:
    tracks = _compile_body_action(body_action)
    matching = [track for track in tracks if track.channel is channel and track.pose]

    assert matching
    assert getattr(matching[0].pose, axis) == pytest.approx(target)
    assert matching[0].motion is None
    assert matching[0].continuity.value == "current"
    assert matching[0].hold is True


@pytest.mark.parametrize(
    ("body_action", "channel", "intent_name"),
    [
        ("left_hand_wave", AvatarTrackChannel.LEFT_ARM, "wave"),
        ("head_circle", AvatarTrackChannel.HEAD, "head_circle"),
        ("jump", AvatarTrackChannel.TORSO, "jump"),
        ("bow", AvatarTrackChannel.TORSO, "bow"),
    ],
)
def test_trajectory_command_keeps_procedural_motion_generator(
    body_action: str,
    channel: AvatarTrackChannel,
    intent_name: str,
) -> None:
    tracks = _compile_body_action(body_action)
    matching = [track for track in tracks if track.channel is channel and track.motion]

    assert matching
    assert matching[0].motion is not None
    assert matching[0].motion.name == intent_name


def test_living_body_runtime_generates_visible_idle_tracks_without_activity() -> None:
    runtime = LivingBodyRuntime(None)

    plan = runtime._build_autonomous_plan(None)
    motions = {
        track.motion.name: track.motion
        for track in plan.tracks
        if track.motion is not None
    }

    assert {
        "breathing",
        "micro_sway",
        "idle_blink",
        "idle_gaze_shift",
        "idle_posture_adjust",
    }.issubset(motions)
    assert motions["breathing"].amplitude >= 0.6
    assert motions["micro_sway"].amplitude >= 0.45


def test_stick_model_supports_pose_targets_and_living_idle() -> None:
    source = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
        / "body-runtime-motions.js"
    ).read_text(encoding="utf-8")

    for name in (
        "idle_blink",
        "idle_gaze_shift",
        "idle_posture_adjust",
        "head_circle",
        "bow",
        "jump",
        "body_sway",
        "body_twist",
        "applyPoseTarget",
        "right_arm_raise",
        "eye_closure",
        "mouth_open",
    ):
        assert name in source
    assert "eyeClosure" in source
    assert "mouthOpen" in source


def _compile_body_action(body_action: str):
    request = SpeechCoupledBodyExpressionRequest(
        source_activity_id="activity-1",
        output_unit_id="output-1",
        expression=EmbodiedExpressionIntent(
            attitude="neutral",
            intensity=0.3,
        ),
        body_actions=(body_action,),
        duration_hint_ms=2400,
    )
    return ConversationalBodyExpressionPlanner().compile(
        request,
        activity_context=BodyActivityContext(
            source_activity_id="activity-1",
            engagement=0.6,
            movement_energy=0.4,
        ),
        segment_index=0,
        start_offset_ms=0,
        duration_ms=2400,
    )


def _activity_with_target(target_type: str, target_id: str) -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="アバター身体命令に応答する",
        activity_id="activity-1",
        context={
            "constraints": {
                "_internal_directive": {
                    "structured_input_meaning": {
                        "input_speech_act": "command",
                        "primary_intent": "アバター身体を操作する",
                        "expected_response": "action",
                        "target": {"type": target_type, "id": target_id},
                        "confidence": 0.96,
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
