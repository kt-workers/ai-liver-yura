"""姿勢記録の三面図、親子座標と表示境界を確認する。"""

from dataclasses import replace
from html.parser import HTMLParser

import pytest

from app.subsystems.validation.body_visualization import render_body_pose_sequence
from app.subsystems.validation.contracts import LabMode, RunStatus
from tests.domain.body_solver.d10_fixtures import physical_model
from tests.subsystems.avatar.test_avatar_presentation import _frame
from tests.subsystems.validation.json_values import array_at, value_at
from tests.subsystems.validation.test_body_execution import runner_for, setup
from tests.subsystems.validation.test_runtime import FIXTURE, spec


class Elements(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def test_three_views_preserve_parent_child_edges_and_escape_identifiers() -> None:
    model = physical_model()
    frame = replace(_frame(1), frame_id='pose:</p><script>alert("x")</script>')
    source = render_body_pose_sequence(model, (frame,), max_frames=2, max_bytes=200_000)
    tags = Elements(source).tags
    assert sum(tag == "script" for tag, _ in tags) == 1
    assert frame.frame_id not in source
    assert sum(tag == "circle" for tag, _ in tags) == 3 * len(model.joints)
    assert sum(tag == "line" and attrs.get("class") == "bone" for tag, attrs in tags) == (
        3 * (len(model.joints) - 1)
    )
    assert not [attrs for _, attrs in tags if "src" in attrs or "href" in attrs]


def test_all_frames_share_a_scale_and_root_movement_remains_visible() -> None:
    frame = _frame(1)
    root = frame.pose.root_world_transform
    moved_root = replace(root, position=replace(root.position, x=root.position.x + 0.5))
    later = replace(_frame(2), pose=replace(frame.pose, root_world_transform=moved_root))
    source = render_body_pose_sequence(
        physical_model(), (frame, later), max_frames=2, max_bytes=200_000
    )
    circles = [attrs for tag, attrs in Elements(source).tags if tag == "circle"]
    count = len(physical_model().joints) * 3
    x_before = circles[0]["cx"]
    x_after = circles[count]["cx"]
    assert x_before is not None and x_after is not None
    assert float(x_after) > float(x_before)


@pytest.mark.parametrize("max_frames,max_bytes", [(1, 200_000), (2, 10)])
def test_visualization_limits_reject_excess_without_truncating_record(
    max_frames: int, max_bytes: int
) -> None:
    with pytest.raises(ValueError):
        render_body_pose_sequence(
            physical_model(), (_frame(1), _frame(2)), max_frames=max_frames, max_bytes=max_bytes
        )


def test_reversed_revision_is_not_presented_as_a_continuous_record() -> None:
    with pytest.raises(ValueError, match="記録順"):
        render_body_pose_sequence(
            physical_model(), (_frame(2), _frame(1)), max_frames=2, max_bytes=200_000
        )


@pytest.mark.asyncio
async def test_actual_body_execution_outputs_visualization_for_every_recorded_pose() -> None:
    case, _ = setup()
    case = replace(case, visualize=True)
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case).run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT), case.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    source = value_at(output, "visualization_html")
    assert isinstance(source, str)
    tags = Elements(source).tags
    assert sum(tag == "section" for tag, _ in tags) == case.tick_count
    for tick in array_at(output, "ticks"):
        frame_id = value_at(tick, "result", "frame", "frame_id")
        assert isinstance(frame_id, str) and frame_id in source


def test_rotating_joint_moves_its_offset_endpoint_even_when_joint_origin_stays_fixed() -> None:
    from math import cos, sin

    from app.domain.body import Quaternion

    frame = _frame(1)
    local = dict(frame.pose.joint_local_transforms)
    local["arm"] = replace(local["arm"], rotation=Quaternion(0, 0, sin(0.2), cos(0.2)))
    later = replace(
        _frame(2), pose=replace(frame.pose, joint_local_transforms=tuple(local.items()))
    )
    source = render_body_pose_sequence(
        physical_model(), (frame, later), max_frames=2, max_bytes=200_000
    )
    tips = [
        attrs
        for tag, attrs in Elements(source).tags
        if tag == "line" and attrs.get("class") == "effector"
    ]
    assert len(tips) == 6
    assert tips[0]["x1"] == tips[3]["x1"]
    assert tips[0]["y1"] == tips[3]["y1"]
    assert tips[0]["y2"] != tips[3]["y2"]
