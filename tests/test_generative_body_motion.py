from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.domain.body_motion import (
    BodyMotionOperation,
    BodyMotionRequest,
    BodyMotionTiming,
    BodyMotionVector,
)
from app.runtime.body_motion_planner import BodyMotionPlanner
from app.runtime.generative_body_motion_controller import (
    GenerativeBodyMotionController,
)

pytestmark = pytest.mark.unit


def _joint_xy(frame, joint_id: str) -> tuple[float, float]:
    joint = frame.kinematic_pose.joint(joint_id)
    assert joint is not None
    return joint.position.x, joint.position.y


def _advance(
    controller: GenerativeBodyMotionController,
    frames: int,
    *,
    start_ms: int = 0,
):  # type: ignore[no-untyped-def]
    result = None
    for index in range(frames):
        result = controller.tick(
            timestamp_ms=start_ms + index * 33,
            dt_seconds=1.0 / 30.0,
        )
    assert result is not None
    return result


def test_motion_planner_compiles_primitives_without_named_motion_presets() -> None:
    request = BodyMotionRequest.from_payload(
        {
            "operation": "parallel",
            "children": [
                {
                    "operation": "reach",
                    "target": "left_hand",
                    "vector": {"x": -0.4, "y": 1.3, "z": 0.0},
                    "timing": {"duration_seconds": 1.5},
                },
                {
                    "operation": "circle",
                    "target": "right_hand",
                    "pivot": "right_shoulder",
                    "radius": 0.65,
                    "timing": {
                        "duration_seconds": 3.0,
                        "repetitions": 3,
                    },
                },
            ],
        }
    )

    plan = BodyMotionPlanner().compile(request)

    assert plan.duration_seconds == pytest.approx(3.0)
    assert plan.targets == (
        "left_hand",
        "right_hand",
        "right_shoulder",
    )
    assert "right_hand_raise" not in str(plan.as_payload())
    assert "wave" not in str(plan.as_payload())


def test_reach_moves_hand_to_arbitrary_coordinate_and_solves_elbow() -> None:
    controller = GenerativeBodyMotionController(tick_hz=30.0, seed=1)
    baseline = controller.tick(timestamp_ms=0, dt_seconds=1.0 / 30.0)
    base_hand = _joint_xy(baseline, "right_hand")
    base_elbow = _joint_xy(baseline, "right_elbow")
    destination = (0.46, 1.38)

    controller.submit_motion(
        BodyMotionRequest(
            operation=BodyMotionOperation.REACH,
            target="right_hand",
            vector=BodyMotionVector(*destination),
            timing=BodyMotionTiming(duration_seconds=2.4),
        )
    )
    middle = _advance(controller, 36, start_ms=33)
    moved_hand = _joint_xy(middle, "right_hand")
    moved_elbow = _joint_xy(middle, "right_elbow")

    base_distance = abs(base_hand[0] - destination[0]) + abs(
        base_hand[1] - destination[1]
    )
    moved_distance = abs(moved_hand[0] - destination[0]) + abs(
        moved_hand[1] - destination[1]
    )
    assert moved_distance < base_distance * 0.35
    assert moved_elbow != pytest.approx(base_elbow)
    assert middle.kinematic_pose.coordinate_space == "body_local_normalized"


def test_circle_generates_continuous_hand_trajectory_around_shoulder() -> None:
    controller = GenerativeBodyMotionController(tick_hz=30.0, seed=2)
    controller.tick(timestamp_ms=0, dt_seconds=1.0 / 30.0)
    controller.submit_motion(
        BodyMotionRequest(
            operation=BodyMotionOperation.CIRCLE,
            target="right_hand",
            pivot="right_shoulder",
            radius=0.66,
            timing=BodyMotionTiming(
                duration_seconds=4.0,
                repetitions=2,
            ),
        )
    )

    samples: list[tuple[float, float]] = []
    for index in range(1, 121):
        frame = controller.tick(
            timestamp_ms=index * 33,
            dt_seconds=1.0 / 30.0,
        )
        if index % 10 == 0:
            samples.append(_joint_xy(frame, "right_hand"))

    assert max(x for x, _ in samples) - min(x for x, _ in samples) > 0.45
    assert max(y for _, y in samples) - min(y for _, y in samples) > 0.45
    maximum_step = max(
        abs(current[0] - previous[0]) + abs(current[1] - previous[1])
        for previous, current in zip(samples, samples[1:])
    )
    assert maximum_step < 1.1


def test_parallel_and_sequence_compose_independent_limbs() -> None:
    controller = GenerativeBodyMotionController(tick_hz=30.0, seed=3)
    baseline = controller.tick(timestamp_ms=0, dt_seconds=1.0 / 30.0)
    base_left_hand = _joint_xy(baseline, "left_hand")
    base_right_hand = _joint_xy(baseline, "right_hand")
    controller.submit_motion(
        BodyMotionRequest(
            operation=BodyMotionOperation.PARALLEL,
            children=(
                BodyMotionRequest(
                    operation=BodyMotionOperation.REACH,
                    target="left_hand",
                    vector=BodyMotionVector(-0.42, 1.34, 0.0),
                    timing=BodyMotionTiming(duration_seconds=2.0),
                ),
                BodyMotionRequest(
                    operation=BodyMotionOperation.REACH,
                    target="right_hand",
                    vector=BodyMotionVector(0.56, 1.12, 0.0),
                    timing=BodyMotionTiming(duration_seconds=2.0),
                ),
            ),
        )
    )
    parallel = _advance(controller, 30, start_ms=33)
    assert _joint_xy(parallel, "left_hand")[1] > base_left_hand[1] + 0.5
    assert _joint_xy(parallel, "right_hand")[1] > base_right_hand[1] + 0.45

    controller.clear_motions(release_holds=True)
    baseline = _advance(controller, 45, start_ms=1100)
    base_left_ankle = _joint_xy(baseline, "left_ankle")
    base_right_ankle = _joint_xy(baseline, "right_ankle")
    controller.submit_motion(
        BodyMotionRequest(
            operation=BodyMotionOperation.SEQUENCE,
            children=(
                BodyMotionRequest(
                    operation=BodyMotionOperation.REACH,
                    target="left_ankle",
                    vector=BodyMotionVector(-0.28, -0.45, 0.0),
                    timing=BodyMotionTiming(duration_seconds=1.2),
                ),
                BodyMotionRequest(
                    operation=BodyMotionOperation.REACH,
                    target="right_ankle",
                    vector=BodyMotionVector(0.28, -0.45, 0.0),
                    timing=BodyMotionTiming(duration_seconds=1.2),
                ),
            ),
        )
    )
    first_half = _advance(controller, 18, start_ms=2600)
    assert _joint_xy(first_half, "left_ankle")[1] > base_left_ankle[1] + 0.25
    assert abs(_joint_xy(first_half, "right_ankle")[1] - base_right_ankle[1]) < 0.12
    second_half = _advance(controller, 40, start_ms=3200)
    assert _joint_xy(second_half, "right_ankle")[1] > base_right_ankle[1] + 0.20


def test_hold_final_and_release_keep_then_restore_generated_pose() -> None:
    controller = GenerativeBodyMotionController(tick_hz=30.0, seed=4)
    baseline = controller.tick(timestamp_ms=0, dt_seconds=1.0 / 30.0)
    base_hand = _joint_xy(baseline, "left_hand")
    controller.submit_motion(
        BodyMotionRequest(
            operation=BodyMotionOperation.REACH,
            target="left_hand",
            vector=BodyMotionVector(-0.44, 1.32, 0.0),
            timing=BodyMotionTiming(duration_seconds=1.0, hold_final=True),
        )
    )
    held_frame = _advance(controller, 40, start_ms=33)
    assert "left_hand" in held_frame.held_targets
    held_hand = _joint_xy(held_frame, "left_hand")
    later = _advance(controller, 30, start_ms=1500)
    assert _joint_xy(later, "left_hand") == pytest.approx(held_hand, abs=0.04)

    controller.submit_motion(
        BodyMotionRequest(
            operation=BodyMotionOperation.RELEASE,
            target="left_hand",
        )
    )
    restored = _advance(controller, 45, start_ms=2600)
    restored_hand = _joint_xy(restored, "left_hand")
    assert "left_hand" not in restored.held_targets
    assert abs(restored_hand[1] - base_hand[1]) < 0.12


def test_body_pose_lab_exposes_generic_motion_api_and_direct_entrypoint() -> None:
    root = Path(__file__).parents[1]
    server_path = root / "gui" / "yura-body-pose-lab" / "server.py"
    spec = importlib.util.spec_from_file_location("generative_body_lab", server_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hub = module.BodyPoseLabHub(tick_hz=30.0)

    plan = hub.submit_motion(
        {
            "operation": "translate",
            "target": "root",
            "vector": {"x": 0.2, "y": 0.1, "z": 0.0},
            "timing": {"duration_seconds": 1.0},
        }
    )
    frame = hub.snapshot()

    assert plan.root.operation is BodyMotionOperation.TRANSLATE
    assert frame.kinematic_pose.joint("right_hand") is not None
    server_text = server_path.read_text(encoding="utf-8")
    index_text = (
        root / "gui" / "yura-body-pose-lab" / "web" / "index.html"
    ).read_text(encoding="utf-8")
    controls_text = (
        root
        / "gui"
        / "yura-body-pose-lab"
        / "web"
        / "body-motion-controls.js"
    ).read_text(encoding="utf-8")
    skeleton_text = (
        root
        / "gui"
        / "yura-body-pose-lab"
        / "web"
        / "body-pose-skeleton.js"
    ).read_text(encoding="utf-8")

    assert 'path == "/api/motion"' in server_text
    assert "GenerativeBodyMotionController" in server_text
    assert 'src="/body-motion-controls.js"' in index_text
    assert 'postJson("/api/motion"' in controls_text
    assert "frame?.kinematic_pose" in skeleton_text
