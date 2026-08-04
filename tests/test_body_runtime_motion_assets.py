from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_stick_model_supports_body_owned_conversation_motion() -> None:
    path = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
        / "body-runtime-motions.js"
    )
    source = path.read_text(encoding="utf-8")

    assert 'case "speech_cadence"' in source
    assert 'case "speech_sway"' in source
    assert 'case "question_tilt"' in source
    assert 'case "breathing"' in source
    assert 'case "micro_sway"' in source
    assert "bodyParticipation" in source
