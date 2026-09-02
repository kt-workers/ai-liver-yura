from __future__ import annotations

import time
from collections.abc import Callable
from typing import cast

from jsonschema.validators import validator_for

from gui.v2_body_avatar_verification.runtime import (
    VerificationEngine,
    body_motion_candidate_output_schema,
)


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if any(not isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _wait_for(
    engine: VerificationEngine,
    predicate: Callable[[dict[str, object]], bool],
    *,
    timeout: float = 4.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = engine.snapshot()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f"verification engine timeout: {engine.snapshot()}")


def test_live_llm_output_schema_is_a_valid_strict_json_schema() -> None:
    schema = body_motion_candidate_output_schema()
    validator = validator_for(schema)
    validator.check_schema(schema)
    assert schema["additionalProperties"] is False


def test_browser_verification_engine_keeps_body_running_during_renderer_disconnect() -> None:
    engine = VerificationEngine(tick_hz=90.0)
    engine.start()
    try:
        ready = _wait_for(engine, lambda value: bool(value.get("ready")))
        start_revision = int(cast(int, ready["body_state_revision"]))

        engine.submit_command(
            {
                "action": "submit_motion",
                "mode": "deterministic",
                "delay_seconds": 0.0,
                "target_angle": 0.35,
            }
        )

        def executing_or_completed(value: dict[str, object]) -> bool:
            session = _object_dict(value.get("session"))
            return (
                session is not None
                and session.get("status") in {"executing", "completed"}
                and value.get("projection_command") is not None
            )

        executing = _wait_for(engine, executing_or_completed)
        assert int(cast(int, executing["body_state_revision"])) > start_revision

        engine.submit_command({"action": "renderer", "available": False})

        def renderer_unavailable(value: dict[str, object]) -> bool:
            avatar = _object_dict(value.get("avatar"))
            return avatar is not None and avatar.get("status") == "output_unavailable"

        unavailable = _wait_for(engine, renderer_unavailable)
        disconnected_revision = int(cast(int, unavailable["body_state_revision"]))
        advanced = _wait_for(
            engine,
            lambda value: isinstance(value.get("body_state_revision"), int)
            and cast(int, value["body_state_revision"]) >= disconnected_revision + 3,
        )
        assert advanced["renderer_available"] is False

        engine.submit_command({"action": "renderer", "available": True})

        def renderer_recovered(value: dict[str, object]) -> bool:
            avatar = _object_dict(value.get("avatar"))
            return (
                value.get("renderer_available") is True
                and avatar is not None
                and avatar.get("status") in {"applied", "partially_applied"}
            )

        recovered = _wait_for(engine, renderer_recovered)
        assert recovered["projection_command"] is not None
    finally:
        engine.stop()
