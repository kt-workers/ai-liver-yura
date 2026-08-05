from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from app.adapters.avatar.http_body_pose_output import (
    HttpBodyPoseFrameOutput,
    HttpBodyPoseOutputConfig,
)
from app.bootstrap import body_runtime_setup
from app.domain.body import (
    BodyActivityContext,
    BodyPostureTendency,
    EmbodiedExpressionIntent,
)
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.runtime.body_pose_3d_projector import KinematicProceduralBodyController
from app.runtime.body_runtime import BodyRuntimeConfig
from app.runtime.core_body_pose_runtime import CoreBodyPoseRuntime

pytestmark = pytest.mark.unit


class _CaptureBodyPoseOutput:
    def __init__(self) -> None:
        self.frames = []
        self.closed = False

    async def publish_body_pose_frame(self, frame: object) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_core_runtime_publishes_continuous_frames_from_activity_context() -> None:
    output = _CaptureBodyPoseOutput()
    runtime = CoreBodyPoseRuntime(
        None,
        body_pose_output=output,
        config=BodyRuntimeConfig(tick_hz=30.0),
    )
    await runtime.update_activity_context(
        BodyActivityContext(
            source_activity_id="conversation",
            attention_target="right",
            engagement=0.9,
            posture_tendency=BodyPostureTendency.FORWARD,
            movement_energy=0.65,
            gaze_freedom=0.8,
        )
    )

    for index in range(40):
        await runtime.tick_once(now=10.0 + index / 30.0)

    assert len(output.frames) == 40
    assert output.frames[-1].sequence == 40
    assert output.frames[-1].attention_target_id == "right"
    assert output.frames[-1].pose.gaze_x > 0.15
    assert output.frames[-1].joints
    assert output.frames[-1].blend_shapes


@pytest.mark.asyncio
async def test_core_body_action_moves_mock_frame_without_avatar_output() -> None:
    output = _CaptureBodyPoseOutput()
    runtime = CoreBodyPoseRuntime(
        None,
        body_pose_output=output,
        config=BodyRuntimeConfig(tick_hz=30.0),
    )
    request = SpeechCoupledBodyExpressionRequest(
        source_activity_id="operator-command",
        output_unit_id="body-command",
        expression=EmbodiedExpressionIntent(
            attitude="friendly",
            intensity=0.8,
            arousal=0.6,
            warmth=0.8,
        ),
        body_actions=("right_hand_wave",),
        duration_hint_ms=2800,
    )
    await runtime.request_expression(request)

    for index in range(45):
        await runtime.tick_once(now=20.0 + index / 30.0)

    raises = [frame.pose.right_arm_raise for frame in output.frames]
    inward = [frame.pose.right_arm_in for frame in output.frames]
    assert max(raises) > 0.55
    assert max(inward) - min(inward) > 0.12


@pytest.mark.asyncio
async def test_http_output_sends_latest_body_pose_payload() -> None:
    sent: list[tuple[str, dict[str, object], float]] = []

    def sender(url: str, body: bytes, timeout: float) -> None:
        sent.append((url, json.loads(body.decode("utf-8")), timeout))

    output = HttpBodyPoseFrameOutput(
        HttpBodyPoseOutputConfig(
            base_url="http://127.0.0.1:8010",
            timeout_seconds=0.5,
        ),
        send_json=sender,
    )
    controller = KinematicProceduralBodyController(tick_hz=30.0, seed=4)
    frame = controller.tick(timestamp_ms=1000, dt_seconds=1.0 / 30.0)

    await output.publish_body_pose_frame(frame)
    for _ in range(20):
        if sent:
            break
        await asyncio.sleep(0.01)
    await output.close()

    assert sent
    url, payload, timeout = sent[-1]
    assert url == "http://127.0.0.1:8010/api/body-pose-frame"
    assert payload["type"] == "body.pose.frame"
    assert payload["source"] == "yura-core"
    assert payload["sequence"] == frame.sequence
    assert payload["pose"] == frame.pose.as_payload()
    assert timeout == 0.5


def test_core_stick_mock_accepts_core_body_pose_payload() -> None:
    root = Path(__file__).parents[1]
    path = root / "gui" / "yura-core-stick-mock" / "server.py"
    spec = importlib.util.spec_from_file_location("yura_core_stick_mock", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    controller = KinematicProceduralBodyController(tick_hz=30.0, seed=5)
    frame = controller.tick(timestamp_ms=2000, dt_seconds=1.0 / 30.0)
    payload = {"source": "yura-core", **frame.as_payload()}
    accepted = module.CoreStickMockHub().publish(payload)

    assert accepted["sequence"] == frame.sequence
    assert accepted["source"] == "yura-core"
    assert accepted["pose"] == frame.pose.as_payload()


def test_body_runtime_setup_selects_core_pose_runtime_without_avatar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_BODY_RUNTIME_ENABLED", "1")
    monkeypatch.setenv("YURA_BODY_POSE_OUTPUT_URL", "http://127.0.0.1:8010")
    monkeypatch.setattr(body_runtime_setup, "get_bound_avatar_output", lambda: None)

    runtime = body_runtime_setup.create_bound_body_runtime_from_env()
    try:
        assert isinstance(runtime, CoreBodyPoseRuntime)
    finally:
        body_runtime_setup.clear_bound_body_runtime()


def test_core_stick_mock_web_assets_share_body_pose_skeleton() -> None:
    root = Path(__file__).parents[1]
    server = (root / "gui" / "yura-core-stick-mock" / "server.py").read_text(
        encoding="utf-8"
    )
    index = (
        root / "gui" / "yura-core-stick-mock" / "web" / "index.html"
    ).read_text(encoding="utf-8")
    browser = (
        root / "gui" / "yura-core-stick-mock" / "web" / "app.js"
    ).read_text(encoding="utf-8")

    assert '"/api/body-pose-frame"' in server
    assert '"/api/frames"' in server
    assert "SHARED_SKELETON" in server
    assert "Live2Dの代わりに棒人間" in index
    assert 'new EventSource("/api/frames")' in browser
    assert "drawStickPerson(frame)" in browser
