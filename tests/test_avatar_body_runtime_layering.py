from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_body_autonomous_and_activity_context_are_parallel_layers() -> None:
    web_root = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )
    html = (web_root / "index.html").read_text(encoding="utf-8")
    layering = (web_root / "body-runtime-layering.js").read_text(
        encoding="utf-8"
    )

    assert 'src="/body-runtime-layering.js"' in html
    assert "body-autonomous" in layering
    assert "body-activity-context" in layering
    assert "state.bodyLayerPerformances" in layering
    assert "activeBaseTracks(now)" in layering
    assert "receiveBasePerformance(plan, sequence)" in layering
