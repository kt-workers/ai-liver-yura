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


def _motion_intent(name: str) -> dict[str, object]:
    return {
        "type": "motion",
        "name": name,
        "intensity": 0.8,
        "amplitude": 0.8,
        "tempo": 1.2,
        "repetitions": 3,
        "body_participation": 0.4,
        "direction": "horizontal",
    }


def _track_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "type": "avatar.performance.submit",
        "performance_id": "performance-1",
        "source_activity_id": "activity-1",
        "output_unit_id": "output-1",
        "priority": 500,
        "interrupt_policy": "replace_lower_priority",
        "return_behavior": "hold",
        "duration_ms": 3000,
        "tracks": [
            {
                "track_id": "expression",
                "channel": "expression",
                "start_offset_ms": 0,
                "duration_ms": 3000,
                "fade_in_ms": 100,
                "fade_out_ms": 150,
                "blend_mode": "override",
                "continuity": "current",
                "hold": True,
                "layer_priority": 100,
                "intent": {
                    "type": "expression",
                    "name": "disgusted",
                    "intensity": 0.9,
                },
            },
            {
                "track_id": "attention",
                "channel": "attention",
                "start_offset_ms": 0,
                "duration_ms": 3000,
                "fade_in_ms": 120,
                "fade_out_ms": 180,
                "blend_mode": "override",
                "continuity": "current",
                "hold": True,
                "layer_priority": 110,
                "intent": {
                    "type": "attention",
                    "target": "cursor",
                    "behavior": "maintain",
                    "intensity": 0.9,
                    "eye_follow": 1.0,
                    "head_follow": 0.6,
                    "body_follow": 0.18,
                },
            },
            {
                "track_id": "head-shake",
                "channel": "head",
                "start_offset_ms": 180,
                "duration_ms": 1400,
                "fade_in_ms": 100,
                "fade_out_ms": 220,
                "blend_mode": "additive",
                "continuity": "current",
                "hold": False,
                "layer_priority": 220,
                "intent": _motion_intent("head_shake"),
            },
            {
                "track_id": "lean-back",
                "channel": "torso",
                "start_offset_ms": 100,
                "duration_ms": 1800,
                "fade_in_ms": 140,
                "fade_out_ms": 300,
                "blend_mode": "additive",
                "continuity": "current",
                "hold": False,
                "layer_priority": 180,
                "intent": {
                    **_motion_intent("lean_back"),
                    "repetitions": 1,
                    "direction": "back",
                },
            },
        ],
        "segments": [],
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

    assert expression["name"] == "happy"
    assert gaze["target"] == "viewer"
    assert gaze["intensity"] == 0.8


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": 2, "type": "avatar.action", "action": "gesture"},
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
    ],
)
def test_validate_avatar_action_rejects_invalid_payload(payload: object) -> None:
    server = _load_server_module()
    with pytest.raises(ValueError):
        server.validate_avatar_action(payload)


def test_validate_avatar_performance_accepts_overlapping_tracks() -> None:
    server = _load_server_module()
    performance = server.validate_avatar_performance(_track_payload())

    assert performance["schema_version"] == 2
    assert performance["duration_ms"] == 3000
    assert len(performance["tracks"]) == 4
    assert performance["tracks"][1]["intent"]["target"] == "cursor"
    assert performance["tracks"][2]["start_offset_ms"] == 180
    assert performance["tracks"][2]["blend_mode"] == "additive"
    assert performance["tracks"][3]["start_offset_ms"] < (
        performance["tracks"][2]["start_offset_ms"]
        + performance["tracks"][2]["duration_ms"]
    )


@pytest.mark.parametrize(
    "update",
    [
        {"type": "avatar.action"},
        {"schema_version": 3},
        {"priority": True},
        {"priority": 1001},
        {"interrupt_policy": "unknown"},
        {"return_behavior": "unknown"},
        {"tracks": [], "segments": []},
        {"duration_ms": 200},
        {
            "tracks": [
                {
                    "track_id": "invalid",
                    "channel": "unknown",
                    "start_offset_ms": 0,
                    "duration_ms": 1000,
                    "intent": _motion_intent("head_shake"),
                }
            ]
        },
        {
            "tracks": [
                {
                    "track_id": "invalid",
                    "channel": "head",
                    "start_offset_ms": 0,
                    "duration_ms": 1000,
                    "fade_in_ms": 100,
                    "fade_out_ms": 100,
                    "blend_mode": "additive",
                    "continuity": "current",
                    "hold": False,
                    "layer_priority": 0,
                    "intent": {
                        "type": "expression",
                        "name": "happy",
                        "intensity": 1.0,
                    },
                }
            ]
        },
    ],
)
def test_validate_avatar_performance_rejects_invalid_payload(
    update: dict[str, object],
) -> None:
    server = _load_server_module()
    payload = _track_payload()
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
    assert snapshot["gesture"] == f"gesture_{server.MAX_HISTORY_ITEMS + 4}"
    assert len(snapshot["history"]) == server.MAX_HISTORY_ITEMS


def test_avatar_state_hub_publishes_track_performance_as_one_event() -> None:
    server = _load_server_module()
    hub = server.AvatarStateHub()
    performance = server.validate_avatar_performance(_track_payload())

    snapshot = hub.publish_performance(performance)

    assert snapshot["sequence"] == 1
    assert snapshot["latest_event_kind"] == "performance"
    assert snapshot["latest_performance"] == performance
    assert snapshot["expression"] == "disgusted"
    assert snapshot["gaze"]["target"] == "cursor"
    assert snapshot["history"][0]["kind"] == "performance"


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
    assert "position: sticky" in css


def test_motion_probe_uses_overlapping_tracks_and_cursor_attention() -> None:
    web_root = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )
    html = (web_root / "index.html").read_text(encoding="utf-8")
    app_js = (web_root / "app.js").read_text(encoding="utf-8")

    assert 'id="performanceDemoButton"' in html
    assert 'id="affirmDemoButton"' in html
    assert 'id="attentionDemoButton"' in html
    assert 'fetch("/api/avatar/performances"' in app_js
    assert "function evaluateTracks" in app_js
    assert "function resolveAttentionTarget" in app_js
    assert 'case "cursor"' in app_js
    assert "const deadZone = 0.08" in app_js
    assert 'case "head_shake"' in app_js
    assert 'case "nod"' in app_js
    assert 'case "draw_in"' in app_js
    assert "state.heldTracks" in app_js
    assert "playSegment(index + 1)" not in app_js
