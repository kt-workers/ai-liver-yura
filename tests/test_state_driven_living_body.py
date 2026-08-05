from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    BodyPostureTendency,
    EmbodiedExpressionIntent,
    SpeechPresentationRequest,
)
from app.domain.body_pose_frame import BodyPoseFrame
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
