from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _web_root() -> Path:
    return (
        Path(__file__).parents[1]
        / "gui"
        / "yura-body-pose-lab"
        / "web"
    )


def test_attention_markers_support_pointer_and_touch_dragging() -> None:
    app = (_web_root() / "app.js").read_text(encoding="utf-8")
    styles = (_web_root() / "styles.css").read_text(encoding="utf-8")

    assert 'marker.addEventListener("pointerdown"' in app
    assert 'marker.addEventListener("pointermove"' in app
    assert "marker.setPointerCapture" in app
    assert "candidate.x = clamp" in app
    assert "candidate.y = clamp" in app
    assert 'postJson("/api/candidates"' in app
    assert "CANDIDATE_POST_INTERVAL_MS = 80" in app
    assert "touch-action: none" in styles
    assert "cursor: grab" in styles
    assert ".target-dot.dragging" in styles


def test_head_center_does_not_translate_sideways_from_yaw() -> None:
    app = (_web_root() / "app.js").read_text(encoding="utf-8")
    skeleton = (_web_root() / "body-pose-skeleton.js").read_text(
        encoding="utf-8"
    )

    assert "rotatePoint(pose.head_yaw * 20" not in app
    assert "rotatePoint(pose.head_yaw * 20" not in skeleton
    assert "headRadiusX = 70 * (1 - Math.abs(pose.head_yaw)" in skeleton


def test_mobile_floating_preview_keeps_avatar_visible_after_scroll() -> None:
    root = _web_root()
    app = (root / "app.js").read_text(encoding="utf-8")
    html = (root / "index.html").read_text(encoding="utf-8")
    styles = (root / "styles.css").read_text(encoding="utf-8")

    assert 'id="floatingPreview"' in html
    assert 'id="floatingCanvas"' in html
    assert "new IntersectionObserver" in app
    assert 'window.matchMedia("(max-width: 980px)")' in app
    assert "floatingCtx.drawImage" in app
    assert ".floating-preview" in styles
    assert "position: fixed" in styles
    assert "env(safe-area-inset-top" in styles


def test_stick_figure_uses_articulated_joint_skeleton() -> None:
    root = _web_root()
    html = (root / "index.html").read_text(encoding="utf-8")
    skeleton = (root / "body-pose-skeleton.js").read_text(encoding="utf-8")

    assert 'src="/body-pose-skeleton.js"' in html
    assert html.index('src="/app.js"') < html.index('src="/body-pose-skeleton.js"')
    assert "function drawJoint(" in skeleton
    assert "function drawJointedArm(" in skeleton
    assert "function drawJointedLeg(" in skeleton
    assert "const elbowX" in skeleton
    assert "const kneeX" in skeleton
    assert "drawJoint(elbowX, elbowY" in skeleton
    assert "drawJoint(kneeX, kneeY" in skeleton


def test_neck_and_shoulders_are_separate_articulated_sections() -> None:
    skeleton = (_web_root() / "body-pose-skeleton.js").read_text(
        encoding="utf-8"
    )

    assert "const shoulderCenterX" in skeleton
    assert "const neckX" in skeleton
    assert "line(shoulderCenterX, shoulderCenterY, neckX, neckY" in skeleton
    assert "line(neckX, neckY, headBottomX, headBottomY" in skeleton
    assert "drawJoint(shoulderCenterX, shoulderCenterY" in skeleton
    assert "drawJoint(neckX, neckY" in skeleton


def test_torso_is_rendered_as_upper_and_lower_triangles() -> None:
    skeleton = (_web_root() / "body-pose-skeleton.js").read_text(
        encoding="utf-8"
    )

    assert "function drawTorsoTriangle(" in skeleton
    assert skeleton.count("drawTorsoTriangle(") >= 3
    assert "leftShoulderX" in skeleton
    assert "rightShoulderX" in skeleton
    assert "waistX" in skeleton
    assert "leftHipX" in skeleton
    assert "rightHipX" in skeleton
    assert "drawJoint(waistX, waistY" in skeleton


def test_body_command_probe_is_loaded_after_core_lab_script() -> None:
    root = _web_root()
    html = (root / "index.html").read_text(encoding="utf-8")
    controls = (root / "body-command-controls.js").read_text(encoding="utf-8")
    styles = (root / "body-command-controls.css").read_text(encoding="utf-8")

    assert 'id="bodyCommandStatus"' in html
    assert 'src="/body-command-controls.js"' in html
    assert html.index('src="/app.js"') < html.index('src="/body-command-controls.js"')
    assert 'data-body-command="right_hand_raise"' in html
    assert 'data-body-command="body_move_up"' in html
    assert 'data-body-command="body_move_down"' in html
    assert 'data-body-command="body_move_left"' in html
    assert 'data-body-command="body_move_right"' in html
    assert 'data-body-command="body_twist"' not in html
    assert 'postJson("/api/body-command"' in controls
    assert ".body-command-grid" in styles
