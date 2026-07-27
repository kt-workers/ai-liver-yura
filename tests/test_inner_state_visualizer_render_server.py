from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_render_server_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-inner-state-visualizer"
        / "render_server.py"
    )
    spec = importlib.util.spec_from_file_location("yura_inner_state_render_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


render_server = _load_render_server_module()


class RecordingSimulator:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def apply_stimulus(self, payload: dict[str, Any], *, now: float) -> bool:
        del now
        self.payloads.append(payload)
        return True


def test_direct_stimulus_gateway_forwards_gesture_without_udp() -> None:
    simulator = RecordingSimulator()
    gateway = render_server.DirectStimulusGateway(
        simulator,
        minimum_interval_seconds=0.0,
    )

    assert gateway.send_stimulus(
        "drag",
        0.8,
        0.7,
        start_position=(0.2, 0.3),
        duration_ms=900,
    )
    assert simulator.payloads == [
        {
            "schema_version": 1,
            "type": "interaction_stimulus",
            "stimulus_kind": "drag",
            "position": {"x": 0.8, "y": 0.7},
            "start_position": {"x": 0.2, "y": 0.3},
            "duration_ms": 900,
        }
    ]


def test_direct_stimulus_gateway_throttles_same_kind() -> None:
    simulator = RecordingSimulator()
    gateway = render_server.DirectStimulusGateway(
        simulator,
        minimum_interval_seconds=60.0,
    )

    assert gateway.send_stimulus("tap", 0.25, 0.75)
    assert not gateway.send_stimulus("tap", 0.5, 0.5)
    assert len(simulator.payloads) == 1
