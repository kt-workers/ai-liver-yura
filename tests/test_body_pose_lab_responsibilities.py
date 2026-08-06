from __future__ import annotations

from pathlib import Path
from queue import Empty

import pytest

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_auxiliary_projection import (
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.domain.body_motion_state import BodyInnerMotionState
from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseAxis,
    BodyPoseConstraintTarget,
)
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.emotions.emotion_state import EmotionState, ReactiveEmotionState
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.state_driven_body_controller import StateDrivenBodyController
from gui.body_pose_lab.api_controller import BodyPoseLabApiController
from gui.body_pose_lab.application import BodyPoseLabApplicationService
from gui.body_pose_lab.composition import BodyPoseLabComposition
from gui.body_pose_lab.config import BodyPoseLabConfig
from gui.body_pose_lab.frame_hub import BodyPoseLabFrameHub
from gui.body_pose_lab.payload_decoder import (
    BodyPoseLabPayloadDecoder,
    BodyPoseLabPayloadError,
)
from gui.body_pose_lab.static_files import BodyPoseLabStaticFiles
from gui.body_pose_lab.tick_loop import BodyPoseLabTickLoop


def make_frame(sequence: int, *, head_yaw: float = 0.0) -> BodyPoseFrame:
    return BodyPoseFrame(
        sequence=sequence,
        timestamp_ms=sequence * 100,
        pose=BodyTrackingPose(head_yaw=head_yaw),
        velocity=BodyTrackingVelocity(),
        inner_state=BodyInnerMotionState(),
    )


def make_application() -> tuple[
    BodyPoseLabApplicationService,
    BodyPoseLabFrameHub,
    BodyPoseLabTickLoop,
]:
    emotion = EmotionState()
    context = BodyActivityContext(
        source_activity_id="lab-test",
        attention_target="user",
    )
    builder = BodyExpressionInputBuilder()
    controller = StateDrivenBodyController(
        builder.build(emotion=emotion, context=context),
        tick_hz=30.0,
        seed=7,
    )
    hub = BodyPoseLabFrameHub()
    application = BodyPoseLabApplicationService(
        controller=controller,
        frame_hub=hub,
        initial_emotion=emotion,
        initial_context=context,
        input_builder=builder,
    )
    return application, hub, BodyPoseLabTickLoop(application)


def test_frame_hub_rejects_stale_frames_and_keeps_latest_for_slow_subscriber() -> None:
    hub = BodyPoseLabFrameHub(maximum_subscribers=2)
    subscription = hub.subscribe()

    assert hub.publish(make_frame(1), source="core", received_at_ms=1000) is True
    assert hub.publish(make_frame(2), source="core", received_at_ms=1100) is True
    assert hub.publish(make_frame(3), source="core", received_at_ms=1200) is True
    assert hub.publish(make_frame(2), source="core", received_at_ms=1300) is False

    published = subscription.queue.get_nowait()
    assert published.frame.sequence == 3
    subscription.queue.task_done()
    with pytest.raises(Empty):
        subscription.queue.get_nowait()

    snapshot = hub.snapshot()
    assert snapshot.received_count == 3
    assert snapshot.stale_count == 1
    assert snapshot.dropped_delivery_count == 2
    assert snapshot.subscriber_count == 1
    hub.unsubscribe(subscription.subscription_id)
    assert hub.snapshot().subscriber_count == 0


def test_payload_decoder_round_trips_body_pose_frame() -> None:
    decoder = BodyPoseLabPayloadDecoder()
    original = make_frame(4, head_yaw=0.42)

    restored = decoder.decode_frame(original.as_payload())

    assert restored == original


def test_payload_decoder_rejects_invalid_non_domain_values() -> None:
    decoder = BodyPoseLabPayloadDecoder()

    with pytest.raises(BodyPoseLabPayloadError):
        decoder.decode_emotion({"arousal": 2.0})
    with pytest.raises(BodyPoseLabPayloadError):
        decoder.decode_external_constraint(
            {
                "constraint_id": "bad",
                "duration_ms": 100,
                "targets": [
                    {"axis": "right_arm_raise", "value": 1.2}
                ],
            }
        )


def test_application_applies_emotion_candidates_and_temporary_constraint() -> None:
    application, hub, _ = make_application()
    application.update_emotion(
        EmotionState(
            arousal=0.8,
            valence=0.7,
            reactive=ReactiveEmotionState(joy=0.9),
        )
    )
    application.update_attention_candidates(
        [
            BodyAttentionCandidate(
                "user",
                x=0.5,
                y=-0.2,
                salience=1.0,
                relevance=1.0,
            )
        ]
    )
    application.apply_external_constraint(
        BodyExternalConstraint(
            constraint_id="raise-right-arm",
            duration_ms=1500,
            targets=(
                BodyPoseConstraintTarget(
                    BodyPoseAxis.RIGHT_ARM_RAISE,
                    0.95,
                ),
            ),
        )
    )

    frames = [
        application.tick_once(timestamp_ms=index * 100, dt_seconds=0.1)
        for index in range(1, 7)
    ]

    assert frames[-1].pose.right_arm_raise > 0.15
    assert frames[-1].inner_state.arousal > 0.5
    assert hub.latest() is not None
    snapshot = application.snapshot()
    assert snapshot.emotion.reactive.joy == 0.9
    assert snapshot.attention_candidates[0].candidate_id == "user"
    assert snapshot.active_constraint_id == "raise-right-arm"


def test_api_controller_keeps_http_routing_out_of_application() -> None:
    application, hub, tick_loop = make_application()
    api = BodyPoseLabApiController(
        application=application,
        frame_hub=hub,
        tick_loop=tick_loop,
    )

    response = api.handle(
        "POST",
        "/api/emotion",
        {
            "mood": "happy",
            "arousal": 0.7,
            "valence": 0.6,
            "talkativeness": 0.5,
            "reactive": {"joy": 0.8},
        },
    )
    assert response.status == 202
    assert application.snapshot().emotion.reactive.joy == 0.8

    invalid = api.handle("POST", "/api/emotion", {"arousal": "high"})
    assert invalid.status == 400
    assert invalid.payload["error"] == "invalid_request"

    frame = make_frame(10)
    accepted = api.handle(
        "POST",
        "/api/body-pose-frame",
        {"source": "core", **frame.as_payload()},
    )
    stale = api.handle(
        "POST",
        "/api/body-pose-frame",
        {"source": "core", **frame.as_payload()},
    )
    assert accepted.status == 202
    assert stale.status == 200
    assert stale.payload["reason"] == "stale_sequence"


def test_static_files_reject_path_traversal(tmp_path: Path) -> None:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("<h1>lab</h1>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    static_files = BodyPoseLabStaticFiles(web_root)

    index = static_files.resolve("/")
    assert index is not None
    assert index.content == b"<h1>lab</h1>"
    assert static_files.resolve("/../secret.txt") is None
    assert static_files.resolve("/%2e%2e/secret.txt") is None


def test_composition_builds_current_controller_without_monkeypatch(
    tmp_path: Path,
) -> None:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("lab", encoding="utf-8")
    components = BodyPoseLabComposition.create(
        BodyPoseLabConfig(port=0, local_simulation=False),
        web_root=web_root,
    )
    try:
        assert components.http_server.address[1] > 0
        frame = components.application.tick_once(dt_seconds=1.0 / 30.0)
        assert frame.sequence == 1
        assert components.frame_hub.latest() is not None
    finally:
        components.http_server.close()
