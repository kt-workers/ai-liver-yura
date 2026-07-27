from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_server_module() -> ModuleType:
    path = Path(__file__).parents[1] / "gui" / "yura-inner-state-visualizer" / "server.py"
    spec = importlib.util.spec_from_file_location("yura_inner_state_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server_module = _load_server_module()


def test_visualizer_stimulus_gateway_forwards_tap_and_throttles() -> None:
    datagrams: list[tuple[bytes, tuple[str, int]]] = []
    gateway = server_module.StimulusGateway(
        "127.0.0.1",
        18771,
        send_datagram=lambda packet, address: datagrams.append((packet, address)),
    )

    assert gateway.send_tap(0.25, 0.75) is True
    assert gateway.send_tap(0.5, 0.5) is False

    packet, address = datagrams[0]
    assert address == ("127.0.0.1", 18771)
    assert json.loads(packet) == {
        "schema_version": 1,
        "type": "interaction_stimulus",
        "stimulus_kind": "tap",
        "position": {"x": 0.25, "y": 0.75},
    }


def test_visualizer_stimulus_gateway_preserves_gesture_details() -> None:
    datagrams: list[tuple[bytes, tuple[str, int]]] = []
    gateway = server_module.StimulusGateway(
        "127.0.0.1",
        18771,
        send_datagram=lambda packet, address: datagrams.append((packet, address)),
    )

    assert gateway.send_stimulus("double_tap", 0.4, 0.6) is True
    assert (
        gateway.send_stimulus(
            "long_press",
            0.5,
            0.5,
            duration_ms=800,
        )
        is True
    )
    assert (
        gateway.send_stimulus(
            "drag",
            0.8,
            0.7,
            start_position=(0.2, 0.3),
            duration_ms=900,
        )
        is True
    )

    payloads = [json.loads(packet) for packet, _ in datagrams]
    assert [payload["stimulus_kind"] for payload in payloads] == [
        "double_tap",
        "long_press",
        "drag",
    ]
    assert payloads[1]["duration_ms"] == 800
    assert payloads[2]["start_position"] == {"x": 0.2, "y": 0.3}
    assert payloads[2]["position"] == {"x": 0.8, "y": 0.7}


def test_visualizer_stimulus_gateway_forwards_continuous_drag_samples() -> None:
    datagrams: list[tuple[bytes, tuple[str, int]]] = []
    gateway = server_module.StimulusGateway(
        "127.0.0.1",
        18771,
        drag_stream_minimum_interval_seconds=0,
        send_datagram=lambda packet, address: datagrams.append((packet, address)),
    )

    samples = [
        ("start", 0, (0.40, 0.50), (0.44, 0.49), 120),
        ("update", 1, (0.44, 0.49), (0.49, 0.47), 260),
        ("end", 2, (0.49, 0.47), (0.53, 0.46), 390),
    ]
    for phase, sequence, start, position, duration_ms in samples:
        assert gateway.send_stimulus(
            "drag",
            position[0],
            position[1],
            start_position=start,
            duration_ms=duration_ms,
            gesture_id="drag-test",
            gesture_phase=phase,
            gesture_sequence=sequence,
            particle_zone={
                "center": {"x": 0.5, "y": 0.49},
                "radius_x": 0.2,
                "radius_y": 0.3,
            },
        )

    payloads = [json.loads(packet) for packet, _ in datagrams]
    assert [payload["gesture_phase"] for payload in payloads] == [
        "start",
        "update",
        "end",
    ]
    assert [payload["gesture_sequence"] for payload in payloads] == [0, 1, 2]
    assert all(payload["gesture_id"] == "drag-test" for payload in payloads)
    assert payloads[1]["start_position"] == {"x": 0.44, "y": 0.49}
    assert payloads[1]["position"] == {"x": 0.49, "y": 0.47}
    assert payloads[1]["duration_ms"] == 260
    assert payloads[1]["particle_zone"] == {
        "center": {"x": 0.5, "y": 0.49},
        "radius_x": 0.2,
        "radius_y": 0.3,
    }
