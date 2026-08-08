from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WEB_JS = (
    _REPOSITORY_ROOT
    / "gui"
    / "yura-body-pose-lab"
    / "web"
    / "js"
)
_GEOMETRY_MODULE = _WEB_JS / "stick-figure-geometry.js"
_FILTER_MODULE = _WEB_JS / "stick-figure-pose-filter.js"
_NODE = shutil.which("node")


def _run_node(script: str) -> object:
    if _NODE is None:
        pytest.skip("node is required for browser geometry validation")
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


def _geometry(pose: dict[str, float]) -> dict[str, object]:
    return _run_node(
        f"""
import {{ computeStickFigureGeometry }} from {json.dumps(_GEOMETRY_MODULE.as_uri())};
const geometry = computeStickFigureGeometry({json.dumps(pose)}, 800, 600);
console.log(JSON.stringify(geometry));
"""
    )


def test_front_view_maps_anatomical_left_to_viewer_right() -> None:
    geometry = _geometry({})
    center_x = geometry["pelvis"]["x"]

    assert geometry["shoulderLeft"]["x"] > center_x
    assert geometry["shoulderRight"]["x"] < center_x
    assert geometry["hipLeft"]["x"] > center_x
    assert geometry["hipRight"]["x"] < center_x


def test_neutral_arms_extend_outward_and_downward_symmetrically() -> None:
    geometry = _geometry({})
    left = geometry["leftArm"]
    right = geometry["rightArm"]
    center_x = geometry["pelvis"]["x"]

    assert left["elbow"]["x"] > left["shoulder"]["x"]
    assert right["elbow"]["x"] < right["shoulder"]["x"]
    assert left["elbow"]["y"] > left["shoulder"]["y"]
    assert right["elbow"]["y"] > right["shoulder"]["y"]
    assert left["wrist"]["x"] > left["elbow"]["x"]
    assert right["wrist"]["x"] < right["elbow"]["x"]
    assert left["elbow"]["x"] - center_x == pytest.approx(
        center_x - right["elbow"]["x"],
    )
    assert left["elbow"]["y"] == pytest.approx(right["elbow"]["y"])


def test_raised_arms_extend_outward_and_upward() -> None:
    geometry = _geometry({"left_arm_raise": 1.0, "right_arm_raise": 1.0})
    left = geometry["leftArm"]
    right = geometry["rightArm"]

    assert left["elbow"]["x"] > left["shoulder"]["x"]
    assert right["elbow"]["x"] < right["shoulder"]["x"]
    assert left["elbow"]["y"] < left["shoulder"]["y"]
    assert right["elbow"]["y"] < right["shoulder"]["y"]


def test_single_arm_raise_keeps_anatomical_side_identity_in_front_view() -> None:
    neutral = _geometry({})
    left_raised = _geometry({"left_arm_raise": 1.0})
    right_raised = _geometry({"right_arm_raise": 1.0})
    center_x = neutral["pelvis"]["x"]

    assert left_raised["leftArm"]["shoulder"]["x"] > center_x
    assert left_raised["leftArm"]["elbow"]["y"] < neutral["leftArm"]["elbow"]["y"]
    assert left_raised["rightArm"]["elbow"]["y"] == pytest.approx(
        neutral["rightArm"]["elbow"]["y"],
    )

    assert right_raised["rightArm"]["shoulder"]["x"] < center_x
    assert right_raised["rightArm"]["elbow"]["y"] < neutral["rightArm"]["elbow"]["y"]
    assert right_raised["leftArm"]["elbow"]["y"] == pytest.approx(
        neutral["leftArm"]["elbow"]["y"],
    )


def test_head_neck_and_torso_share_one_connected_centerline() -> None:
    geometry = _geometry({})

    assert geometry["chest"]["x"] == pytest.approx(geometry["pelvis"]["x"])
    assert geometry["neck"]["x"] == pytest.approx(geometry["chest"]["x"])
    assert geometry["head"]["x"] == pytest.approx(geometry["neck"]["x"])
    assert geometry["headBottom"]["y"] > geometry["head"]["y"]
    assert geometry["headBottom"]["y"] < geometry["neck"]["y"]


def test_pose_filter_suppresses_subpixel_jitter() -> None:
    result = _run_node(
        f"""
import {{ StickFigurePoseFilter }} from {json.dumps(_FILTER_MODULE.as_uri())};
const filter = new StickFigurePoseFilter();
filter.apply({{ torso_roll: 0, head_yaw: 0, body_height: 0 }});
const values = [0.0004, -0.0003, 0.0005, -0.0004].map((value) =>
  filter.apply({{ torso_roll: value, head_yaw: value, body_height: value }})
);
console.log(JSON.stringify(values));
"""
    )

    assert all(sample["torso_roll"] == pytest.approx(0.0) for sample in result)
    assert all(sample["head_yaw"] == pytest.approx(0.0) for sample in result)
    assert max(abs(sample["body_height"]) for sample in result) < 0.0005


def test_pose_filter_tracks_large_intentional_motion_without_freezing() -> None:
    result = _run_node(
        f"""
import {{ StickFigurePoseFilter }} from {json.dumps(_FILTER_MODULE.as_uri())};
const filter = new StickFigurePoseFilter();
filter.apply({{ right_arm_raise: 0 }});
const values = [];
for (let index = 0; index < 5; index += 1) {{
  values.push(filter.apply({{ right_arm_raise: 1 }}).right_arm_raise);
}}
console.log(JSON.stringify(values));
"""
    )

    assert result[0] > 0.15
    assert result[-1] > 0.75
    assert result == sorted(result)
