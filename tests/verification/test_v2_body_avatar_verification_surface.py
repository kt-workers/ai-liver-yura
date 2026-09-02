from __future__ import annotations

import time
from collections.abc import Callable
from typing import cast

from jsonschema.validators import validator_for

from gui.v2_body_avatar_verification import VerificationEngine
from gui.v2_body_avatar_verification.realtime_runtime import (
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


def _frame_channels(value: dict[str, object]) -> dict[str, object]:
    frame = _object_dict(value.get("frame"))
    if frame is None:
        return {}
    channels = _object_dict(frame.get("channels"))
    return {} if channels is None else channels


def test_live_llm_output_schema_is_a_valid_strict_json_schema() -> None:
    schema = body_motion_candidate_output_schema()
    validator = validator_for(schema)
    validator.check_schema(schema)
    assert schema["additionalProperties"] is False


def test_browser_surface_uses_340_realtime_runtime_without_direct_channel_overlay() -> None:
    engine = VerificationEngine(tick_hz=45.0)
    engine.start()
    try:
        def realtime_ready(value: dict[str, object]) -> bool:
            realtime = _object_dict(value.get("realtime"))
            channels = _frame_channels(value)
            return (
                bool(value.get("ready"))
                and realtime is not None
                and realtime.get("runtime") == "BodyRealtimeRuntime"
                and realtime.get("engine") == "BodyRealtimeEngine"
                and realtime.get("browser_direct_channel_overlay") is False
                and {"eyelid_openness", "breath_phase", "breath_amplitude", "subtle_sway"}
                <= set(channels)
            )

        ready = _wait_for(engine, realtime_ready)
        realtime = _object_dict(ready["realtime"])
        assert realtime is not None
        statuses = _object_dict(realtime.get("layer_statuses"))
        assert statuses is not None
        assert statuses.get("blink") == "active"
        assert statuses.get("breath") == "active"
        assert statuses.get("subtle_motion") in {"active", "inactive_no_source"}

        engine.submit_command({"action": "channels", "gaze_x": 1.0, "gaze_y": -1.0})

        def smoothed_gaze(value: dict[str, object]) -> bool:
            channels = _frame_channels(value)
            x = channels.get("gaze_x")
            y = channels.get("gaze_y")
            return (
                isinstance(x, (int, float))
                and not isinstance(x, bool)
                and isinstance(y, (int, float))
                and not isinstance(y, bool)
                and 0.0 < float(x) < 1.0
                and -1.0 < float(y) < 0.0
            )

        _wait_for(engine, smoothed_gaze)
    finally:
        engine.stop()


def test_trusted_speech_timing_sample_flows_through_340_to_avatar_channels() -> None:
    engine = VerificationEngine(tick_hz=45.0)
    engine.start()
    try:
        _wait_for(engine, lambda value: bool(value.get("ready")))
        engine.submit_command({"action": "speech"})

        def speaking(value: dict[str, object]) -> bool:
            realtime = _object_dict(value.get("realtime"))
            channels = _frame_channels(value)
            openness = channels.get("mouth_openness")
            return (
                realtime is not None
                and realtime.get("speech_sample_active") is True
                and isinstance(openness, (int, float))
                and not isinstance(openness, bool)
                and float(openness) > 0.0
            )

        observed = _wait_for(engine, speaking)
        realtime = _object_dict(observed["realtime"])
        assert realtime is not None
        statuses = _object_dict(realtime.get("layer_statuses"))
        assert statuses is not None
        assert statuses.get("speech_articulation") == "active"
        projection = _object_dict(observed.get("projection_command"))
        assert projection is not None
        channel_projections = projection.get("channel_projections")
        assert isinstance(channel_projections, list)
        assert any(
            isinstance(item, dict)
            and item.get("canonical_channel") == "mouth_openness"
            and isinstance(item.get("value"), (int, float))
            and not isinstance(item.get("value"), bool)
            and float(cast(float, item["value"])) > 0.0
            for item in channel_projections
        )
    finally:
        engine.stop()


def test_browser_verification_engine_keeps_body_running_during_renderer_disconnect() -> None:
    engine = VerificationEngine(tick_hz=45.0)
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
        realtime = _object_dict(advanced.get("realtime"))
        assert realtime is not None and realtime.get("runtime") == "BodyRealtimeRuntime"

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
