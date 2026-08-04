from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_current_performance_label_keeps_stage_height_stable() -> None:
    web_root = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )
    html = (web_root / "index.html").read_text(encoding="utf-8")
    css = (web_root / "layout-stability.css").read_text(encoding="utf-8")

    assert 'href="/layout-stability.css"' in html
    assert ".stage-toolbar" in css
    assert "min-height: 84px" in css
    assert "#performanceLabel" in css
    assert "white-space: nowrap" in css
    assert "text-overflow: ellipsis" in css
    assert ".stage-toolbar > div:first-child" in css
    assert "min-width: 0" in css
