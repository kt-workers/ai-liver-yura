from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_runtime_loads_pose_continuity_after_layer_composer() -> None:
    web_root = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )
    html = (web_root / "index.html").read_text(encoding="utf-8")

    layering_index = html.index('src="/body-runtime-layering.js"')
    continuity_index = html.index('src="/body-runtime-continuity.js"')
    mobile_index = html.index('src="/mobile-preview.js"')

    assert layering_index < continuity_index < mobile_index


def test_continuity_runtime_uses_current_pose_and_reveals_lower_layers() -> None:
    source = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
        / "body-runtime-continuity.js"
    ).read_text(encoding="utf-8")

    assert "state.pose" in source
    assert 'track.continuity !== "current"' in source
    assert "track.__continuityOrigin" in source
    assert "continuityOriginWeight" in source
    assert "remaining / fadeOut" in source
    assert "state.transition = null" in source
    assert "layer_priority" in source
    assert "state.__continuityChannels" in source
