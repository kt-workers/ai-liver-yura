from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest


def _load_simulator_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-inner-state-visualizer"
        / "simulator.py"
    )
    spec = importlib.util.spec_from_file_location("yura_inner_state_simulator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


simulator_module = _load_simulator_module()


def _stimulus(kind: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "interaction_stimulus",
        "stimulus_kind": kind,
        "position": {"x": 0.4, "y": 0.6},
    }


@pytest.mark.parametrize(
    ("kind", "reactive_name"),
    [
        ("tap", "surprise"),
        ("double_tap", "surprise"),
        ("long_press", "joy"),
        ("drag", "amusement"),
    ],
)
def test_interactive_simulator_applies_core_gesture_appraisal(
    kind: str,
    reactive_name: str,
) -> None:
    simulator = simulator_module.InteractiveStateSimulator(now=100.0)

    assert simulator.apply_stimulus(_stimulus(kind), now=100.0) is True
    snapshot = simulator.snapshot(
        now=100.0,
        observed_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert snapshot["emotion"]["reactive"][reactive_name] > 0
    assert snapshot["emotion"]["arousal"] > 0.5
    assert snapshot["drive"]["engagement"] == pytest.approx(0.58)
    assert snapshot["activity"] == {
        "type": f"stimulus_{kind}",
        "active": True,
        "pending_count": 0,
    }
    assert snapshot["attention"] == {"engaged": True}


def test_interactive_simulator_rejects_invalid_stimulus() -> None:
    simulator = simulator_module.InteractiveStateSimulator(now=100.0)
    invalid = _stimulus("tap")
    invalid["position"] = {"x": 2.0, "y": 0.5}

    assert simulator.apply_stimulus(invalid, now=100.0) is False
    assert simulator.emotion.arousal == 0.5


def test_interactive_simulator_clears_reaction_activity_after_timeout() -> None:
    simulator = simulator_module.InteractiveStateSimulator(now=100.0)
    simulator.apply_stimulus(_stimulus("tap"), now=100.0)

    snapshot = simulator.snapshot(now=104.0)

    assert snapshot["activity"] == {
        "type": "idle_observation",
        "active": False,
        "pending_count": 0,
    }
    assert snapshot["emotion"]["reactive"]["surprise"] > 0
