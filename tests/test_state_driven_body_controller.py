from __future__ import annotations

import pytest

from app.domain.body_activity_context import (
    BodyActivityContext,
    BodyPostureTendency,
)
from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseAxis,
    BodyPoseConstraintTarget,
)
from app.domain.body_speech import SpeechPresentationRequest
from app.domain.emotions.emotion_state import (
    EmotionState,
    MoodType,
    ReactiveEmotionState,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.state_driven_body_controller import StateDrivenBodyController

pytestmark = pytest.mark.unit


def _intention(kind: InteractionIntentionType) -> InteractionIntention:
    return InteractionIntention(
        intention=kind,
        confidence=0.9,
        source="test",
        reason="controller_test",
        target_type="counterpart",
        target_id="user",
        observation_only=False,
    )


def _input(
    emotion: EmotionState,
    *,
    kind: InteractionIntentionType = InteractionIntentionType.ACKNOWLEDGE,
):
    return BodyExpressionInputBuilder().build(
        emotion=emotion,
        context=BodyActivityContext(
            source_activity_id="activity-1",
            attention_target="user",
            engagement=0.82,
            posture_tendency=BodyPostureTendency.OPEN,
            movement_energy=0.48,
            gaze_freedom=0.24,
            interaction_intention=_intention(kind),
        ),
    )


def _shape(frame, name: str) -> float:
    return next(shape.value for shape in frame.blend_shapes if shape.name == name)


def test_state_driven_controller_emits_continuous_schema_v2_frames() -> None:
    controller = StateDrivenBodyController(
        _input(
            EmotionState(
                mood=MoodType.HAPPY,
                arousal=0.64,
                valence=0.58,
                talkativeness=0.72,
                reactive=ReactiveEmotionState(joy=0.82, amusement=0.35),
            )
        ),
        seed=11,
    )
    controller.set_attention_candidates(
        [BodyAttentionCandidate("user", 0.18, -0.08, relevance=1.0)]
    )

    first = controller.tick(timestamp_ms=1000, dt_seconds=1 / 30)
    later = first
    for index in range(1, 50):
        later = controller.tick(
            timestamp_ms=1000 + index * 33,
            dt_seconds=1 / 30,
        )

    assert first.sequence == 1
    assert later.sequence == 50
    assert later.schema_version == 2
    assert later.attention_target_id == "user"
    assert later.canonical_joint_ids >= {"hips", "head", "left_upper_arm"}
    assert _shape(later, "mouth_smile") > 0.1
    assert _shape(later, "mouth_frown") == pytest.approx(0.0, abs=0.03)
    assert later.pose != first.pose


def test_external_constraint_overlays_emotion_pose_and_returns_continuously() -> None:
    controller = StateDrivenBodyController(
        _input(
            EmotionState(
                mood=MoodType.HAPPY,
                arousal=0.55,
                valence=0.62,
                reactive=ReactiveEmotionState(joy=0.88),
            )
        ),
        seed=17,
    )
    for _ in range(30):
        baseline = controller.tick(dt_seconds=1 / 30)

    controller.apply_external_constraint(
        BodyExternalConstraint(
            constraint_id="right-arm-temporary",
            targets=(
                BodyPoseConstraintTarget(
                    axis=BodyPoseAxis.RIGHT_ARM_RAISE,
                    value=1.0,
                ),
            ),
            duration_ms=800,
        )
    )
    raised_frames = [controller.tick(dt_seconds=1 / 30) for _ in range(14)]
    raised = max(raised_frames, key=lambda value: value.pose.right_arm_raise)

    assert raised.pose.right_arm_raise > baseline.pose.right_arm_raise + 0.15
    assert raised.pose.right_arm_raise > raised.pose.left_arm_raise
    assert _shape(raised, "mouth_smile") > 0.1

    for _ in range(70):
        returned = controller.tick(dt_seconds=1 / 30)

    assert controller.active_constraint_id is None
    assert returned.pose.right_arm_raise < raised.pose.right_arm_raise
    assert _shape(returned, "mouth_smile") > 0.1


def test_speech_mouth_is_combined_with_existing_facial_expression() -> None:
    controller = StateDrivenBodyController(
        _input(
            EmotionState(
                mood=MoodType.HAPPY,
                arousal=0.50,
                valence=0.48,
                reactive=ReactiveEmotionState(amusement=0.72),
            )
        ),
        seed=19,
    )
    for _ in range(20):
        controller.tick(dt_seconds=1 / 30)
    request = SpeechPresentationRequest(
        source_activity_id="activity-1",
        output_unit_id="speech-1",
        text="うれしいな",
        audio_reference="memory://speech-1",
        duration_ms=600,
    )
    controller.present_speech(request, energy=0.8)

    speaking = controller.tick(dt_seconds=1 / 30)

    assert controller.active_speech_id == request.presentation_id
    assert speaking.pose.mouth_open > 0.1
    assert _shape(speaking, "mouth_smile") > 0.05

    for _ in range(30):
        completed = controller.tick(dt_seconds=1 / 30)

    assert controller.active_speech_id is None
    assert completed.pose.mouth_open < speaking.pose.mouth_open


def test_updating_expression_input_changes_emotion_baseline_without_resetting_pose() -> None:
    controller = StateDrivenBodyController(
        _input(
            EmotionState(
                mood=MoodType.HAPPY,
                arousal=0.55,
                valence=0.62,
                reactive=ReactiveEmotionState(joy=0.84),
            )
        ),
        seed=23,
    )
    for _ in range(45):
        happy = controller.tick(dt_seconds=1 / 30)

    controller.update_expression_input(
        _input(
            EmotionState(
                mood=MoodType.SAD,
                arousal=0.28,
                valence=-0.68,
                reactive=ReactiveEmotionState(sadness=0.90),
            ),
            kind=InteractionIntentionType.LISTEN,
        )
    )
    first_sad = controller.tick(dt_seconds=1 / 30)
    for _ in range(60):
        sad = controller.tick(dt_seconds=1 / 30)

    assert first_sad.pose.mouth_form > -0.8
    assert sad.pose.mouth_form < happy.pose.mouth_form
    assert _shape(sad, "mouth_frown") > _shape(sad, "mouth_smile")
    assert sad.sequence == happy.sequence + 61


def test_forced_blink_does_not_remove_body_posture_or_attention() -> None:
    controller = StateDrivenBodyController(
        _input(EmotionState(), kind=InteractionIntentionType.LISTEN),
        seed=29,
    )
    controller.set_attention_candidates(
        [BodyAttentionCandidate("user", 0.1, 0.0, relevance=1.0)]
    )
    for _ in range(10):
        controller.tick(dt_seconds=1 / 30)
    controller.request_blink()

    blink_frames = [controller.tick(dt_seconds=0.04) for _ in range(5)]

    assert min(frame.pose.eye_left_open for frame in blink_frames) < 0.5
    assert all(frame.attention_target_id == "user" for frame in blink_frames)
    assert all(frame.pose.torso_pitch < 0.2 for frame in blink_frames)
