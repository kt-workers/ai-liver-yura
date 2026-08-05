from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from app.bootstrap.body_runtime_setup import create_bound_body_runtime_from_env
from app.domain.actions import ActionPlan, ActionType
from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    SpeechPresentationRequest,
)
from app.domain.body_motion import (
    BodyMotionOperation,
    BodyMotionRequest,
    BodyMotionTiming,
    BodyMotionVector,
)
from app.domain.body_runtime import BodyRuntimeSnapshot
from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    StructuredInputMeaning,
)
from app.ports.avatar_output import bind_avatar_output
from app.ports.body_pose_output import BodyPoseFrameOutputPort
from app.ports.body_subsystem import BodySubsystemPort, bind_body_subsystem
from app.runtime.body_motion_request_resolver import (
    body_motion_request_from_meaning,
    normalize_body_motion_meaning,
)
from app.runtime.core_generative_body_runtime import CoreGenerativeBodyRuntime
from app.usecases import ExecuteActionUsecase

pytestmark = pytest.mark.unit


class FakePoseOutput:
    def __init__(self) -> None:
        self.frames: list[object] = []
        self.closed = False

    async def publish_body_pose_frame(self, frame: object) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        self.closed = True


class FakeBodySubsystem:
    def __init__(self) -> None:
        self.motions: list[BodyMotionRequest] = []
        self.contexts: list[BodyActivityContext] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def update_activity_context(self, context: BodyActivityContext) -> None:
        self.contexts.append(context)

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        del request

    async def request_motion(self, request: BodyMotionRequest) -> None:
        self.motions.append(request)

    async def present_speech(self, request: SpeechPresentationRequest) -> None:
        del request

    async def snapshot(self) -> BodyRuntimeSnapshot:
        return BodyRuntimeSnapshot(
            running=True,
            tick_count=0,
            active_activity_id=None,
            pending_expression_count=0,
            active_speech_id=None,
            last_performance_id=None,
            last_error=None,
        )


@pytest.fixture(autouse=True)
def reset_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    bind_avatar_output(None)
    bind_body_subsystem(None)
    for key in (
        "YURA_BODY_RUNTIME_ENABLED",
        "YURA_BODY_POSE_OUTPUT_URL",
        "YURA_BODY_POSE_OUTPUT_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    yield
    bind_avatar_output(None)
    bind_body_subsystem(None)


def _meaning(text: str) -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.COMMAND,
        primary_intent="move_avatar_body",
        expected_response=ExpectedResponse.ACTION,
        target=None,
        source_text=text,
    )


def test_body_command_is_composed_as_motion_primitives_not_named_preset() -> None:
    normalized = normalize_body_motion_meaning(
        _meaning("右手を上に1.5秒かけて伸ばして、そのまま止めて")
    )

    assert normalized.target is not None
    assert normalized.target.target_type == "body_motion"
    request = body_motion_request_from_meaning(normalized)
    assert request is not None
    assert request.operation is BodyMotionOperation.REACH
    assert request.target == "right_hand"
    assert request.vector is not None
    assert request.vector.y > 1.0
    assert request.timing.duration_seconds == pytest.approx(1.5)
    assert request.timing.hold_final is True
    assert "right_hand_raise" not in str(normalized.as_context())


def test_ordered_body_command_becomes_sequence() -> None:
    request = body_motion_request_from_meaning(
        _meaning("右手を前に伸ばしてから、左手を上に伸ばして")
    )

    assert request is not None
    assert request.operation is BodyMotionOperation.SEQUENCE
    assert [child.target for child in request.children] == [
        "right_hand",
        "left_hand",
    ]
    assert all(child.operation is BodyMotionOperation.REACH for child in request.children)


@pytest.mark.asyncio
async def test_core_runtime_generates_kinematic_frames_from_motion_request() -> None:
    output = FakePoseOutput()
    runtime = CoreGenerativeBodyRuntime(
        None,
        body_pose_output=cast(BodyPoseFrameOutputPort, output),
    )
    await runtime.request_motion(
        BodyMotionRequest(
            operation=BodyMotionOperation.REACH,
            target="right_hand",
            vector=BodyMotionVector(0.66, 1.22, 0.25),
            timing=BodyMotionTiming(duration_seconds=1.0, hold_final=True),
            motion_id="core-right-hand-reach",
        )
    )

    for index in range(36):
        await runtime.tick_once(now=10.0 + index / 30.0)

    assert output.frames
    frame = output.frames[-1]
    payload = frame.as_payload()  # type: ignore[attr-defined]
    assert payload["kinematic_pose"]
    joints = {
        item["joint_id"]: item["position"]
        for item in payload["kinematic_pose"]["joints"]
    }
    assert joints["right_hand"]["y"] > 1.0
    assert payload["motion_schema_version"] == 1
    assert "right_hand" in payload["held_targets"]


@pytest.mark.asyncio
async def test_execute_action_routes_motion_request_to_bound_core_body() -> None:
    body = FakeBodySubsystem()
    usecase = ExecuteActionUsecase(
        body_subsystem=cast(BodySubsystemPort, body),
    )
    request = BodyMotionRequest(
        operation=BodyMotionOperation.OSCILLATE,
        target="left_hand",
        vector=BodyMotionVector(0.2, 0.0, 0.0),
        timing=BodyMotionTiming(duration_seconds=1.2, repetitions=2),
        motion_id="left-hand-oscillate",
    )
    context = BodyActivityContext(
        source_activity_id="activity-1",
        engagement=0.7,
    )
    action = ActionPlan(
        action_type=ActionType.OBSERVE,
        text="",
        source_activity_id="activity-1",
        output_unit_id="output-1",
        metadata={
            "body_activity_context": context,
            "body_motion_request": request,
        },
    )

    await usecase.execute(action)
    await usecase.execute(action)

    assert body.motions == [request]
    assert body.contexts == [context]


def test_bootstrap_selects_core_generative_runtime_for_pose_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_BODY_RUNTIME_ENABLED", "1")
    monkeypatch.setenv("YURA_BODY_POSE_OUTPUT_URL", "http://127.0.0.1:8010")

    runtime = create_bound_body_runtime_from_env()

    assert isinstance(runtime, CoreGenerativeBodyRuntime)


def test_stick_mock_only_renders_core_pose_frames() -> None:
    root = Path(__file__).parents[1] / "gui" / "yura-core-stick-mock"
    server = (root / "server.py").read_text(encoding="utf-8")
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "GenerativeBodyMotionController" not in server
    assert "BodyMotionRequest" not in server
    assert 'path != "/api/body-pose-frame"' in server
    assert "const pose = frame?.kinematic_pose" in app
    assert "EventSource(\"/api/events\")" in app
    assert "動作の解釈・軌道・IKは実行しません" in readme
