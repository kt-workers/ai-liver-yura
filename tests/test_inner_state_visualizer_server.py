from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_server_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-inner-state-visualizer"
        / "server.py"
    )
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
