from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest


def _load_server_module() -> ModuleType:
    module_name = f"avatar_runtime_lab_server_{uuid4().hex}"
    path = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "server.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load avatar runtime lab server")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _performance_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "avatar.performance.submit",
        "performance_id": "performance-1",
        "source_activity_id": "activity-1",
        "output_unit_id": "output-1",
        "priority": 500,
        "interrupt_policy": "replace_lower_priority",
        "return_behavior": "neutral",
        "segments": [
            {
                "expression": {"name": "curious", "intensity": 0.6},
                "gesture": {"name": "head_tilt", "intensity": 0.5},
                "gaze": {
                    "target": "viewer",
                    "behavior": "maintain",
                    "intensity": 0.8,
                },
                "duration_ms": 900,
                "fade_in_ms": 100,
                "fade_out_ms": 150,
            },
            {
                "expression": {"name": "happy", "intensity": 0.9},
                "gesture": {"name": "wave", "intensity": 0.9},
                "gaze": None,
                "duration_ms": 1400,
                "fade_in_ms": 150,
                "fade_out_ms": 250,
            },
        ],
    }


def test_validate_avatar_action_accepts_expression_and_gaze() -> None:
    server = _load_server_module()

    expression = server.validate_avatar_action(
        {
            "schema_version": 1,
            "type": "avatar.action",
            "action": "expression",
            "name": "happy",
            "intensity": 0.7,
        }
    )
    gaze = server.validate_avatar_action(
        {
            "schema_version": 1,
            "type": "avatar.action",
            "action": "gaze",
            "target": "viewer",
            "behavior": "maintain",
            "intensity": 0.8,
        }
    )

    assert expression == {
        "schema_version": 1,
        "type": "avatar.action",
        "action": "expression",
        "name": "happy",
        "intensity": 0.7,
    }
    assert gaze["target"] == "viewer"
    assert gaze["behavior"] == "maintain"
    assert gaze["intensity"] == 0.8


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": 2, "type": "avatar.action", "action": "gesture"},
        {
            "schema_version": 1,
            "type": "unknown",
            "action": "gesture",
            "name": "wave",
        },
        {
            "schema_version": 1,
            "type": "avatar.action",
            "action": "gesture",
            "name": "../../invalid",
        },
        {
            "schema_version": 1,
            "type": "avatar.action",
            "action": "gaze",
            "target": "viewer",
            "behavior": "invalid",
        },
        {
            "schema_version": 1,
            "type": "avatar.action",
            "action": "expression",
            "name": "happy",
            "intensity": 1.1,
        },
    ],
)
def test_validate_avatar_action_rejects_invalid_payload(payload: object) -> None:
    server = _load_server_module()

    with pytest.raises(ValueError):
        server.validate_avatar_action(payload)


def test_validate_avatar_performance_accepts_multiple_segments() -> None:
    server = _load_server_module()

    performance = server.validate_avatar_performance(_performance_payload())

    assert performance["performance_id"] == "performance-1"
    assert performance["priority"] == 500
    assert len(performance["segments"]) == 2
    assert performance["segments"][0]["expression"] == {
        "name": "curious",
        "intensity": 0.6,
    }
    assert performance["segments"][1]["gesture"]["name"] == "wave"
    assert performance["segments"][1]["gaze"] is None


@pytest.mark.parametrize(
    "update",
    [
        {"type": "avatar.action"},
        {"priority": True},
        {"priority": 1001},
        {"interrupt_policy": "unknown"},
        {"return_behavior": "unknown"},
        {"segments": []},
        {"segments": [{}]},
        {
            "segments": [
                {
                    "expression": {"name": "happy", "intensity": 1.2},
                    "gesture": None,
                    "gaze": None,
                    "duration_ms": 1000,
                    "fade_in_ms": 100,
                    "fade_out_ms": 100,
                }
            ]
        },
        {
            "segments": [
                {
                    "expression": {"name": "happy", "intensity": 1.0},
                    "gesture": None,
                    "gaze": None,
                    "duration_ms": 500,
                    "fade_in_ms": 600,
                    "fade_out_ms": 100,
                }
            ]
        },
    ],
)
def test_validate_avatar_performance_rejects_invalid_payload(
    update: dict[str, object],
) -> None:
    server = _load_server_module()
    payload = _performance_payload()
    payload.update(update)

    with pytest.raises(ValueError):
        server.validate_avatar_performance(payload)


def test_avatar_state_hub_updates_state_and_limits_history() -> None:
    server = _load_server_module()
    hub = server.AvatarStateHub()

    first = hub.publish(
        {
            "schema_version": 1,
            "type": "avatar.action",
            "action": "expression",
            "name": "curious",
            "intensity": 1.0,
        }
    )
    for index in range(server.MAX_HISTORY_ITEMS + 5):
        hub.publish(
            {
                "schema_version": 1,
                "type": "avatar.action",
                "action": "gesture",
                "name": f"gesture_{index}",
                "intensity": 1.0,
            }
        )
    snapshot = hub.snapshot()

    assert first["expression"] == "curious"
    assert snapshot["expression"] == "curious"
    assert snapshot["gesture"] == f"gesture_{server.MAX_HISTORY_ITEMS + 4}"
    assert snapshot["sequence"] == server.MAX_HISTORY_ITEMS + 6
    assert len(snapshot["history"]) == server.MAX_HISTORY_ITEMS
    assert snapshot["history"][0]["action"]["name"] == (
        f"gesture_{server.MAX_HISTORY_ITEMS + 4}"
    )


def test_avatar_state_hub_publishes_performance_as_one_event() -> None:
    server = _load_server_module()
    hub = server.AvatarStateHub()
    performance = server.validate_avatar_performance(_performance_payload())

    snapshot = hub.publish_performance(performance)

    assert snapshot["sequence"] == 1
    assert snapshot["latest_event_kind"] == "performance"
    assert snapshot["latest_performance"] == performance
    assert snapshot["expression"] == "curious"
    assert snapshot["gesture"] == "head_tilt"
    assert snapshot["gaze"]["target"] == "viewer"
    assert snapshot["history"][0]["kind"] == "performance"
    assert snapshot["history"][0]["performance"]["segments"][1]["expression"][
        "name"
    ] == "happy"


def test_mobile_manual_controls_keep_avatar_preview_visible() -> None:
    web_root = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )
    html = (web_root / "index.html").read_text(encoding="utf-8")
    css = (web_root / "styles.css").read_text(encoding="utf-8")
    mobile_preview_js = (web_root / "mobile-preview.js").read_text(
        encoding="utf-8"
    )

    assert 'class="mobile-preview"' in html
    assert 'id="mobileAvatarCanvas"' in html
    assert 'src="/mobile-preview.js"' in html
    assert 'matchMedia("(max-width: 1040px)")' in mobile_preview_js
    assert "targetContext.drawImage(source" in mobile_preview_js
    assert "requestAnimationFrame(syncMobilePreview)" in mobile_preview_js
    assert "position: sticky" in css
    assert "safe-area-inset-top" in css


def test_performance_probe_supports_timeline_and_interrupt_policy() -> None:
    web_root = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )
    html = (web_root / "index.html").read_text(encoding="utf-8")
    playback_js = (web_root / "performance-playback.js").read_text(
        encoding="utf-8"
    )

    assert 'id="performanceDemoButton"' in html
    assert 'src="/performance-playback.js"' in html
    assert 'fetch("/api/avatar/performances"' in playback_js
    assert 'plan.interrupt_policy === "queue"' in playback_js
    assert 'plan.interrupt_policy === "ignore_if_busy"' in playback_js
    assert "playSegment(index + 1)" in playback_js
    assert 'behavior === "previous"' in playback_js
    assert 'behavior === "neutral"' in playback_js
