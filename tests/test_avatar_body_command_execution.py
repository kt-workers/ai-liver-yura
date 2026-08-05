from __future__ import annotations

import json

import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.body_motion import BodyMotionOperation, BodyMotionRequest
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
    ("text", "operation", "targets"),
    [
        ("右手を上に伸ばして", BodyMotionOperation.REACH, ("right_hand",)),
        ("左手を左右に2回振って", BodyMotionOperation.OSCILLATE, ("left_hand",)),
        ("両手を上に伸ばして", BodyMotionOperation.PARALLEL, ("left_hand", "right_hand")),
        ("顔をぐるっと回して", BodyMotionOperation.CIRCLE, ("head",)),
        ("胴体を35度ひねって", BodyMotionOperation.ROTATE, ("chest",)),
    ],
)
def test_input_meaning_normalizes_body_commands_to_motion_request(
    text: str,
    operation: BodyMotionOperation,
    targets: tuple[str, ...],
) -> None:
    meaning = InputMeaningJsonParser().parse(
        _meaning_json(text),
        source_text=text,
    )

    assert meaning is not None
    assert meaning.target is not None
    assert meaning.target.target_type == "body_motion"
    entity = next(
        item for item in meaning.entities if item.get("type") == "body_motion_request"
    )
    request = BodyMotionRequest.from_payload(entity["payload"])
    assert request.operation is operation
    resolved_targets = (
        tuple(child.target for child in request.children)
        if request.operation is BodyMotionOperation.PARALLEL
        else (request.target,)
    )
    assert resolved_targets == targets
    assert "right_hand_raise" not in json.dumps(
        meaning.as_context(),
        ensure_ascii=False,
    )


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
        primary_intent="move_avatar_right_hand",
        expected_response=ExpectedResponse.ACTION,
        target=InputTarget("body_motion", "reach"),
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


def test_existence_profile_distinguishes_real_and_avatar_bodies() -> None:
    policies = CharacterExistenceProfile().behavior_policies()

    assert any("現実世界" in item and "物理的な身体を持たない" in item for item in policies)
    assert any("アバター身体" in item and "動かせる" in item for item in policies)
    assert any("Body Subsystem" in item and "実行" in item for item in policies)


def test_action_planner_attaches_motion_request_without_character_gesture() -> None:
    parser = InputMeaningJsonParser()
    meaning = parser.parse(
        _meaning_json("右手を上に1.5秒かけて伸ばして"),
        source_text="右手を上に1.5秒かけて伸ばして",
    )
    assert meaning is not None
    planner = AvatarBodyCommandActionPlanner(UnusedResponseGenerator())
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="アバター身体命令に応答する",
        activity_id="activity-1",
        context={
            "constraints": {
                "_internal_directive": {
                    "structured_input_meaning": meaning.as_context(),
                }
            }
        },
    )
    response = CharacterResponse(
        speech="うん、動かすね。",
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

    request = plans[0].metadata["body_motion_request"]
    assert isinstance(request, BodyMotionRequest)
    assert request.operation is BodyMotionOperation.REACH
    assert request.target == "right_hand"
    assert request.motion_id == "activity-1:output-1:body-motion"
    assert not any("avatar_body_actions" in plan.metadata for plan in plans)
