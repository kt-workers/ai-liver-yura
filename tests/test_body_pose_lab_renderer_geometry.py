from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_GEOMETRY_MODULE = (
    _REPOSITORY_ROOT
    / "gui"
    / "yura-body-pose-lab"
    / "web"
    / "js"
    / "stick-figure-geometry.js"
)
_NODE = shutil.which("node")


def _geometry(pose: dict[str, float]) -> dict[str, object]:
    if _NODE is None:
        pytest.skip("node is required for browser geometry validation")
    script = f"""
import {{ computeStickFigureGeometry }} from {json.dumps(_GEOMETRY_MODULE.as_uri())};
const geometry = computeStickFigureGeometry({json.dumps(pose)}, 800, 600);
console.log(JSON.stringify(geometry));
"""
    completed = subprocess.run(
        [
            _NODE,
            "--experimental-default-type=module",
            "--input-type=module",
            "-e",
            script,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_neutral_arms_extend_outward_and_downward_symmetrically() -> None:
    geometry = _geometry({})
    left = geometry["leftArm"]
    right = geometry["rightArm"]
    center_x = geometry["pelvis"]["x"]

    assert left["elbow"]["x"] < left["shoulder"]["x"]
    assert right["elbow"]["x"] > right["shoulder"]["x"]
    assert left["elbow"]["y"] > left["shoulder"]["y"]
    assert right["elbow"]["y"] > right["shoulder"]["y"]
    assert left["wrist"]["x"] < left["elbow"]["x"]
    assert right["wrist"]["x"] > right["elbow"]["x"]
    assert (center_x - left["elbow"]["x"]) == pytest.approx(
        right["elbow"]["x"] - center_x,
    )
    assert left["elbow"]["y"] == pytest.approx(right["elbow"]["y"])


def test_raised_arms_extend_outward_and_upward() -> None:
    geometry = _geometry({"left_arm_raise": 1.0, "right_arm_raise": 1.0})
    left = geometry["leftArm"]
    right = geometry["rightArm"]

    assert left["elbow"]["x"] < left["shoulder"]["x"]
    assert right["elbow"]["x"] > right["shoulder"]["x"]
    assert left["elbow"]["y"] < left["shoulder"]["y"]
    assert right["elbow"]["y"] < right["shoulder"]["y"]


def test_head_neck_and_torso_share_one_connected_centerline() -> None:
    geometry = _geometry({})

    assert geometry["chest"]["x"] == pytest.approx(geometry["pelvis"]["x"])
    assert geometry["neck"]["x"] == pytest.approx(geometry["chest"]["x"])
    assert geometry["head"]["x"] == pytest.approx(geometry["neck"]["x"])
    assert geometry["headBottom"]["y"] > geometry["head"]["y"]
    assert geometry["headBottom"]["y"] < geometry["neck"]["y"]
