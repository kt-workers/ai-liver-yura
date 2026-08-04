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
