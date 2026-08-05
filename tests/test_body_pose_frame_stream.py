from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.domain.body_pose_frame import (
    BodyAttentionCandidate,
    BodyCoordinateSpace,
    BodyInnerMotionState,
    BodyPoseFrame,
    BodyQuaternion,
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.runtime.body_pose_3d_projector import (
    KinematicProceduralBodyController,
)

pytestmark = pytest.mark.unit


def test_quaternion_is_normalized_and_serializable() -> None:
    quaternion = BodyQuaternion.from_euler_radians(x=0.4, y=-0.7, z=0.2)
    length = math.sqrt(
        quaternion.x * quaternion.x
        + quaternion.y * quaternion.y
        + quaternion.z * quaternion.z
        + quaternion.w * quaternion.w
    )

    assert length == pytest.approx(1.0)
    assert set(quaternion.as_payload()) == {"x", "y", "z", "w"}


def test_body_pose_frame_keeps_generic_3d_and_2d_projection() -> None:
    controller = KinematicProceduralBodyController(tick_hz=30.0, seed=1)
    controller.set_attention_candidates(
        [
            BodyAttentionCandidate(
                "right_object",
                0.8,
                -0.2,
                salience=1.0,
                novelty=0.8,
                relevance=0.9,
            )
        ]
    )

    frame = controller.tick(timestamp_ms=1000, dt_seconds=1.0 / 30.0)
    payload = frame.as_payload()

    assert frame.coordinate_space is BodyCoordinateSpace.RIGHT_HANDED_Y_UP
    assert frame.schema_version == 2
    assert {joint.joint_id for joint in frame.joints} >= {
        "hips",
        "spine",
        "chest",
        "neck",
        "head",
        "left_upper_arm",
        "right_upper_arm",
    }
    assert {shape.name for shape in frame.blend_shapes} >= {
        "eye_blink_left",
        "eye_blink_right",
        "jaw_open",
    }
    assert payload["coordinate_space"] == "right_handed_y_up"
    assert payload["joints"]
    assert payload["blend_shapes"]
    assert payload["gaze_vector"]
    assert payload["pose"]


def test_tracking_continues_from_current_pose_instead_of_home_reset() -> None:
    controller = KinematicProceduralBodyController(
        tick_hz=30.0,
        seed=4,
        inner_state=BodyInnerMotionState(
            curiosity=0.9,
            engagement=0.8,
            movement_energy=0.6,
        ),
    )
    controller.set_attention_candidates(
        [BodyAttentionCandidate("right", 0.92, 0.0, salience=1.0, relevance=1.0)]
    )
    frames: list[BodyPoseFrame] = []
    for index in range(90):
        frames.append(
            controller.tick(
                timestamp_ms=1000 + index * 33,
                dt_seconds=1.0 / 30.0,
            )
        )

    before_removal = frames[-1].pose.head_yaw
    assert before_removal > 0.1
    maximum_step = max(
        abs(current.pose.head_yaw - previous.pose.head_yaw)
        for previous, current in zip(frames, frames[1:])
    )
    assert maximum_step < 0.12

    controller.set_attention_candidates([])
    next_frame = controller.tick(timestamp_ms=4000, dt_seconds=1.0 / 30.0)

    assert abs(next_frame.pose.head_yaw) > 0.01
    assert abs(next_frame.pose.head_yaw - before_removal) < 0.12


def test_frame_rejects_duplicate_canonical_joints() -> None:
    controller = KinematicProceduralBodyController(tick_hz=30.0, seed=2)
    frame = controller.tick(timestamp_ms=1000, dt_seconds=1.0 / 30.0)

    with pytest.raises(ValueError, match="joint ids must be unique"):
        BodyPoseFrame(
            sequence=frame.sequence,
            timestamp_ms=frame.timestamp_ms,
            pose=BodyTrackingPose(),
            velocity=BodyTrackingVelocity(),
            inner_state=BodyInnerMotionState(),
            joints=(frame.joints[0], frame.joints[0]),
        )


def test_render_lab_hub_produces_frames_without_core_llm_or_tts() -> None:
    path = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-body-pose-lab"
        / "server.py"
    )
    spec = importlib.util.spec_from_file_location("yura_body_pose_lab_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hub = module.BodyPoseLabHub(tick_hz=30.0)

    hub.start()
    try:
        first = hub.snapshot()
        second = hub.wait_for_frame(first.sequence, timeout=1.0)
    finally:
        hub.stop()

    assert second.sequence > first.sequence
    assert second.pose != BodyTrackingPose()
    assert second.kinematic_pose.joint("right_hand") is not None


def test_render_entrypoint_imports_app_outside_repository_cwd() -> None:
    root = Path(__file__).parents[1]
    render_server = (
        root / "gui" / "yura-body-pose-lab" / "render_server.py"
    )
    command = (
        "import runpy; "
        f"runpy.run_path({str(render_server)!r}, run_name='render_import_check')"
    )

    with tempfile.TemporaryDirectory() as temporary_directory:
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=temporary_directory,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_render_lab_is_configured_as_standalone_service() -> None:
    root = Path(__file__).parents[1]
    lab_root = root / "gui" / "yura-body-pose-lab"
    render_yaml = (root / "render.yaml").read_text(encoding="utf-8")
    render_server = (lab_root / "render_server.py").read_text(encoding="utf-8")
    server = (lab_root / "server.py").read_text(encoding="utf-8")
    browser = (lab_root / "web" / "app.js").read_text(encoding="utf-8")
    skeleton = (lab_root / "web" / "body-pose-skeleton.js").read_text(
        encoding="utf-8"
    )

    assert "name: yura-body-pose-lab" in render_yaml
    assert "python gui/yura-body-pose-lab/render_server.py" in render_yaml
    assert "GenerativeBodyMotionController" in server
    assert "KinematicProceduralBodyController" not in render_server
    assert "PROJECT_ROOT" in render_server
    assert "sys.path.insert" in render_server
    assert 'new EventSource("/api/frames")' in browser
    assert "frame?.kinematic_pose" in skeleton
    assert 'path == "/api/motion"' in server
    assert "CharacterLlm" not in render_server
    assert "TTS" not in render_server
