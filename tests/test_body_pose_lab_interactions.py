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


def test_head_center_comes_from_canonical_joint_and_yaw_changes_only_width() -> None:
    app = (_web_root() / "app.js").read_text(encoding="utf-8")
    skeleton = (_web_root() / "body-pose-skeleton.js").read_text(
        encoding="utf-8"
    )

    # 旧描画のfallbackでもyawを頭中心の横移動には使わない。
    assert "const neckOffset = rotatePoint(0, -56" in app
    assert "rotatePoint(pose.head_yaw * 20" not in app
    assert "headRadiusX = 72 * (1 - Math.abs(pose.head_yaw)" in app

    # Generative描画ではCanonical head/neck関節を中心座標として使い、yawは幅のみ。
    assert 'const head = points.get("head")' in skeleton
    assert 'const neck = points.get("neck")' in skeleton
    assert "ctx.translate(head.x, head.y)" in skeleton
    assert "head.x +" not in skeleton
    assert "Math.abs(Number(pose.head_yaw) || 0)" in skeleton
    assert "line(neck.x, neck.y, head.x" in skeleton


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


def test_stick_figure_uses_canonical_articulated_joint_skeleton() -> None:
    root = _web_root()
    html = (root / "index.html").read_text(encoding="utf-8")
    skeleton = (root / "body-pose-skeleton.js").read_text(encoding="utf-8")

    assert 'src="/body-pose-skeleton.js"' in html
    assert html.index('src="/app.js"') < html.index('src="/body-pose-skeleton.js"')
    assert "function drawJoint(" in skeleton
    assert "function kinematicView(" in skeleton
    assert "frame?.kinematic_pose" in skeleton
    assert 'points.get("left_elbow")' not in skeleton
    assert 'drawChain(points, ["left_shoulder", "left_elbow", "left_hand"]' in skeleton
    assert 'drawChain(points, ["right_shoulder", "right_elbow", "right_hand"]' in skeleton
    assert 'drawChain(points, ["left_hip", "left_knee", "left_ankle"]' in skeleton
    assert 'drawChain(points, ["right_hip", "right_knee", "right_ankle"]' in skeleton
    assert "drawPolygon([leftShoulder, rightShoulder, pelvis]" in skeleton
    assert "drawPolygon([pelvis, leftHip, rightHip]" in skeleton
    assert "line(chest.x, chest.y, neck.x, neck.y" in skeleton
    assert "line(neck.x, neck.y, head.x" in skeleton
