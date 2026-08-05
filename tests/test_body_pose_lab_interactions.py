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

    assert "const neckOffset = rotatePoint(0, -56" in app
    assert "rotatePoint(pose.head_yaw * 20" not in app
    assert "headRadiusX = 72 * (1 - Math.abs(pose.head_yaw)" in app


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
