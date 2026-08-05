from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.runtime.procedural_body_controller import ProceduralBodyController

pytestmark = pytest.mark.unit


def _tick_many(
    controller: ProceduralBodyController,
    count: int,
    *,
    start_ms: int = 1000,
) -> list[object]:
    return [
        controller.tick(
            timestamp_ms=start_ms + index * 33,
            dt_seconds=1.0 / 30.0,
        )
        for index in range(count)
    ]


def test_hand_raise_is_continuous_and_does_not_start_from_home_reset() -> None:
    controller = ProceduralBodyController(tick_hz=30.0, seed=21)
    before = _tick_many(controller, 20)[-1]
    controller.apply_body_command("right_hand_raise", duration_ms=2400)
    frames = _tick_many(controller, 75, start_ms=2000)

    values = [frame.pose.right_arm_raise for frame in frames]
    assert max(values) > 0.72
    assert abs(values[0] - before.pose.right_arm_raise) < 0.08
    assert max(
        abs(current - previous)
        for previous, current in zip(values, values[1:])
    ) < 0.12


def test_face_commands_change_tracking_values() -> None:
    controller = ProceduralBodyController(tick_hz=30.0, seed=22)

    controller.apply_body_command("eyes_close", duration_ms=2200)
    eye_frames = _tick_many(controller, 45)
    assert min(frame.pose.eye_left_open for frame in eye_frames) < 0.2
    assert min(frame.pose.eye_right_open for frame in eye_frames) < 0.2

    controller.apply_body_command("mouth_open", duration_ms=2200)
    mouth_frames = _tick_many(controller, 45, start_ms=3000)
    assert max(frame.pose.mouth_open for frame in mouth_frames) > 0.68


def test_motion_commands_generate_time_varying_paths() -> None:
    controller = ProceduralBodyController(tick_hz=30.0, seed=23)

    controller.apply_body_command("body_sway", duration_ms=3000)
    sway_frames = _tick_many(controller, 75)
    torso_values = [frame.pose.torso_roll for frame in sway_frames]
    assert max(torso_values) - min(torso_values) > 0.35

    controller.apply_body_command("jump", duration_ms=1800)
    jump_frames = _tick_many(controller, 50, start_ms=4000)
    assert max(frame.pose.body_height for frame in jump_frames) > 0.55


def test_body_command_rejects_unknown_or_invalid_duration() -> None:
    controller = ProceduralBodyController(tick_hz=30.0)

    with pytest.raises(ValueError, match="unsupported body command"):
        controller.apply_body_command("teleport")
    with pytest.raises(ValueError, match="duration_ms"):
        controller.apply_body_command("bow", duration_ms=100)


def test_render_lab_hub_accepts_body_command_without_llm() -> None:
    path = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-body-pose-lab"
        / "server.py"
    )
    spec = importlib.util.spec_from_file_location("body_pose_command_lab", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hub = module.BodyPoseLabHub(tick_hz=30.0)

    command, duration_ms = hub.apply_body_command(
        {"command": "right_hand_wave", "duration_ms": 2800}
    )

    assert command == "right_hand_wave"
    assert duration_ms == 2800
    assert hub.active_body_command == "right_hand_wave"


def test_render_lab_exposes_body_command_api_and_controls() -> None:
    root = Path(__file__).parents[1]
    server = (root / "gui" / "yura-body-pose-lab" / "server.py").read_text(
        encoding="utf-8"
    )
    web = root / "gui" / "yura-body-pose-lab" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    controls = (web / "body-command-controls.js").read_text(encoding="utf-8")

    assert 'path == "/api/body-command"' in server
    assert 'data-body-command="right_hand_raise"' in html
    assert 'data-body-command="eyes_close"' in html
    assert 'data-body-command="jump"' in html
    assert 'postJson("/api/body-command"' in controls
