from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.body import (
    BodyActivityContext,
    BodyAffectContext,
    BodyExpressionRequest,
    BodyPostureTendency,
    EmbodiedExpressionIntent,
    SpeechPresentationRequest,
)
from app.domain.body_pose_frame import BodyPoseFrame
from app.runtime.body_activity_context_builder import BodyActivityContextBuilder
from app.runtime.body_runtime import BodyRuntimeConfig
from app.runtime.state_driven_body_controller import StateDrivenBodyController
from app.runtime.state_driven_body_pose_runtime import StateDrivenBodyPoseRuntime


def _shape_values(frame: BodyPoseFrame) -> dict[str, float]:
    return {shape.name: shape.value for shape in frame.blend_shapes}


def _happy_request() -> BodyExpressionRequest:
    return BodyExpressionRequest(
        source_activity_id="conversation-1",
        output_unit_id="reply-1",
        facial_expression="happy",
        facial_intensity=0.9,
        expression=EmbodiedExpressionIntent(
            attitude="warm_joy",
            intensity=0.88,
            valence=0.82,
            arousal=0.55,
            tension=0.08,
            openness=0.82,
            approach=0.42,
            agreement=0.32,
            surprise=0.08,
            assertiveness=0.48,
            warmth=0.92,
        ),
        duration_hint_ms=1500,
    )


def test_expression_is_composed_with_face_gaze_and_body() -> None:
    controller = StateDrivenBodyController(tick_hz=30.0, seed=7)
    controller.apply_expression(_happy_request())

    frames = [
        controller.tick(timestamp_ms=index * 33, dt_seconds=1.0 / 30.0)
        for index in range(18)
    ]

    assert max(_shape_values(frame)["mouth_smile"] for frame in frames) > 0.45
    assert max(_shape_values(frame)["brow_raise"] for frame in frames) >= 0.0
    assert any(abs(frame.pose.head_pitch) > 0.01 for frame in frames)
    assert any(frame.pose.left_arm_in < 0.0 for frame in frames)
    assert all(frame.joints for frame in frames)
    assert all(frame.gaze_vector.direction.z > 0.0 for frame in frames)


def test_speech_mouth_is_layered_without_removing_expression() -> None:
    controller = StateDrivenBodyController(tick_hz=30.0, seed=11)
    controller.apply_expression(_happy_request())
    controller.set_speech_active(True, energy=0.8)

    frames = [
        controller.tick(timestamp_ms=index * 33, dt_seconds=1.0 / 30.0)
        for index in range(16)
    ]

    assert max(frame.pose.mouth_open for frame in frames) > 0.45
    assert max(_shape_values(frame)["mouth_smile"] for frame in frames) > 0.35
    assert max(_shape_values(frame)["jaw_open"] for frame in frames) > 0.45


def test_emotion_snapshot_shapes_face_without_character_expression() -> None:
    controller = StateDrivenBodyController(tick_hz=30.0, seed=19)
    controller.set_baseline_affect(
        BodyAffectContext(
            valence=-0.72,
            arousal=0.76,
            anger=0.82,
            discomfort=0.58,
            emotional_pressure=0.64,
        )
    )

    frame = controller.tick(timestamp_ms=33, dt_seconds=1.0 / 30.0)
    shapes = _shape_values(frame)

    assert shapes["mouth_frown"] > shapes["mouth_smile"]
    assert shapes["brow_lower"] > 0.25
    assert shapes["eye_squint_left"] > 0.15


def test_activity_builder_projects_event_emotion_and_drive() -> None:
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="人間と会話する",
        context={
            "event_payload": {
                "emotion": {
                    "arousal": 0.84,
                    "valence": -0.48,
                    "reactive": {
                        "joy": 0.05,
                        "amusement": 0.02,
                        "anger": 0.72,
                        "sadness": 0.12,
                        "fear": 0.20,
                        "surprise": 0.08,
                        "discomfort": 0.54,
                        "emotional_pressure": 0.62,
                    },
                },
                "drive": {
                    "curiosity": 0.88,
                    "engagement": 0.91,
                    "boredom": 0.04,
                    "energy": 0.79,
                },
            }
        },
    )

    context = BodyActivityContextBuilder().build(activity)

    assert context.engagement == pytest.approx(0.91)
    assert context.movement_energy == pytest.approx(0.79)
    assert context.gaze_freedom > 0.75
    assert context.affect is not None
    assert context.affect.arousal == pytest.approx(0.84)
    assert context.affect.anger == pytest.approx(0.72)
    assert context.affect.discomfort == pytest.approx(0.54)


@dataclass
class _RecordingPoseOutput:
    frames: list[BodyPoseFrame] = field(default_factory=list)
    closed: bool = False

    async def publish_body_pose_frame(self, frame: BodyPoseFrame) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_runtime_publishes_unified_state_driven_frames() -> None:
    output = _RecordingPoseOutput()
    runtime = StateDrivenBodyPoseRuntime(
        None,
        body_pose_output=output,
        config=BodyRuntimeConfig(
            tick_hz=30.0,
            autonomous_interval_ms=120_000,
            baseline_refresh_ms=120_000,
        ),
    )
    await runtime.update_activity_context(
        BodyActivityContext(
            source_activity_id="conversation-1",
            attention_target="conversation_partner",
            engagement=0.86,
            posture_tendency=BodyPostureTendency.OPEN,
            movement_energy=0.52,
            gaze_freedom=0.28,
            affect=BodyAffectContext(
                valence=0.62,
                arousal=0.58,
                joy=0.72,
                amusement=0.34,
            ),
        )
    )
    await runtime.request_expression(_happy_request())
    await runtime.present_speech(
        SpeechPresentationRequest(
            source_activity_id="conversation-1",
            output_unit_id="reply-1",
            text="うれしいな。",
            audio_reference="memory://reply-1",
            duration_ms=1200,
        )
    )

    for index in range(12):
        await runtime.tick_once(now=index / 30.0)

    assert len(output.frames) == 12
    latest = output.frames[-1]
    shapes = _shape_values(latest)
    assert latest.attention_target_id == "conversation_partner"
    assert shapes["mouth_smile"] > 0.25
    assert shapes["jaw_open"] > 0.20
    assert latest.joints

    await runtime.stop()
    assert output.closed is True
