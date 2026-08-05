from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stick_mock_renders_unified_body_frame_without_deciding_motion() -> None:
    server = (ROOT / "gui/yura-core-stick-mock/server.py").read_text(encoding="utf-8")
    app = (ROOT / "gui/yura-core-stick-mock/web/app.js").read_text(encoding="utf-8")
    readme = (ROOT / "gui/yura-core-stick-mock/README.md").read_text(
        encoding="utf-8"
    )

    assert 'path != "/api/body-pose-frame"' in server
    assert 'new EventSource("/api/events")' in app
    assert 'frame?.blend_shapes || []' in app
    assert "brow_raise" in app
    assert "mouth_smile" in app
    assert "pose.left_arm_raise" in app

    combined = "\n".join((server, app))
    assert "BodyMotionRequest" not in combined
    assert "BodyMotionPlanner" not in combined
    assert "GenerativeBodyMotionController" not in combined
    assert "自然言語の解釈" in readme
    assert "感情や表情の決定" in readme
    assert "プリセット選択" in readme
