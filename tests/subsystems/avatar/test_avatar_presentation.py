from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from math import sqrt

import pytest

from app.domain.body import Axis, BodyPose, JointTransform, Quaternion, Vector3
from app.domain.body_realtime import RealtimeChannel
from app.domain.body_solver import BodyFrameChannelValue, BodyPoseFrame
from app.subsystems.avatar import (
    AvatarCapabilityView,
    AvatarChannelBinding,
    AvatarJointBinding,
    AvatarMirrorPolicy,
    AvatarModelBinding,
    AvatarModelKind,
    AvatarPresentationRuntime,
    AvatarProjectionCommand,
    AvatarProjectionStatus,
    AvatarRendererResult,
    AvatarRendererStatus,
    StickAvatarRenderer,
    project_body_pose_frame,
    validate_avatar_model_binding,
)
from tests.domain.body_solver.d10_fixtures import physical_model, physical_state

NOW = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
ALL_AXES = (Axis.X, Axis.Y, Axis.Z)


def _capability(
    *,
    joints: tuple[str, ...] = ("root", "arm"),
    channels: tuple[RealtimeChannel, ...] = (),
    depth: bool = True,
    root_translation: bool = True,
    face: bool = True,
) -> AvatarCapabilityView:
    return AvatarCapabilityView(
        joints,
        channels,
        ALL_AXES,
        ALL_AXES,
        60.0,
        depth,
        root_translation,
        face,
    )


def _binding(
    *,
    generation: int = 1,
    revision: int = 1,
    kind: AvatarModelKind = AvatarModelKind.STICK,
    mirror: AvatarMirrorPolicy = AvatarMirrorPolicy.NONE,
    joints: tuple[AvatarJointBinding, ...] | None = None,
    channels: tuple[AvatarChannelBinding, ...] = (),
    capability: AvatarCapabilityView | None = None,
) -> AvatarModelBinding:
    joint_bindings = joints or (
        AvatarJointBinding("root", "renderer:root", True, True, ALL_AXES, ALL_AXES),
        AvatarJointBinding("arm", "renderer:arm", True, True, ALL_AXES, ALL_AXES),
    )
    view = capability or _capability(
        joints=tuple(value.canonical_joint_id for value in joint_bindings),
        channels=tuple(value.canonical_channel for value in channels),
    )
    return AvatarModelBinding(
        "binding:test",
        revision,
        generation,
        kind,
        f"model:{kind.value}",
        "body.d10",
        "root",
        joint_bindings,
        channels,
        mirror,
        view,
        NOW,
    )


def _frame(
    revision: int,
    *,
    frame_id: str | None = None,
    root: JointTransform | None = None,
    channels: tuple[BodyFrameChannelValue, ...] = (),
) -> BodyPoseFrame:
    state = physical_state(revision=max(0, revision - 1))
    pose = state.pose
    if root is not None:
        pose = BodyPose(root, pose.joint_local_transforms)
    return BodyPoseFrame(
        frame_id or f"frame:{revision}",
        "body.d10",
        revision,
        NOW + timedelta(milliseconds=revision),
        pose,
        state.velocity,
        "plan:test",
        "trajectory:test",
        channels,
        (),
        (),
        "trace:test",
    )


def test_binding_uses_exact_canonical_ids_and_rejects_unknown_joint() -> None:
    model = physical_model()
    validate_avatar_model_binding(_binding(), model)

    bad = _binding(
        joints=(
            AvatarJointBinding(
                "unknown",
                "renderer:unknown",
                True,
                True,
                ALL_AXES,
                ALL_AXES,
            ),
        ),
        capability=_capability(joints=("unknown",)),
    )
    with pytest.raises(ValueError, match="未知Canonical joint"):
        validate_avatar_model_binding(bad, model)


def test_binding_rejects_duplicate_renderer_target() -> None:
    with pytest.raises(ValueError, match="renderer target"):
        _binding(
            joints=(
                AvatarJointBinding(
                    "root", "renderer:same", True, True, ALL_AXES, ALL_AXES
                ),
                AvatarJointBinding(
                    "arm", "renderer:same", True, True, ALL_AXES, ALL_AXES
                ),
            )
        )


def test_missing_joint_mapping_is_typed_partial_degradation() -> None:
    binding = _binding(
        joints=(
            AvatarJointBinding("root", "renderer:root", True, True, ALL_AXES, ALL_AXES),
        ),
        capability=_capability(joints=("root",)),
    )
    command = project_body_pose_frame(_frame(1), binding, physical_model())

    assert tuple(value.canonical_joint_id for value in command.joint_projections) == ("root",)
    assert "joint:arm:unmapped" in command.degraded_items

    renderer = StickAvatarRenderer()
    runtime = AvatarPresentationRuntime(physical_model(), binding, renderer)
    runtime.submit_frame(_frame(1))
    report = runtime.present_latest(started_at=NOW)
    assert report is not None
    assert report.status is AvatarProjectionStatus.PARTIALLY_APPLIED
    assert "joint:arm:unmapped" in report.degraded_items


def test_camera_mirror_changes_renderer_values_without_swapping_anatomical_ids() -> None:
    q = sqrt(0.5)
    root = JointTransform(Vector3(0.25, 0.1, 0.2), Quaternion(0.0, 0.0, q, q))
    command = project_body_pose_frame(
        _frame(1, root=root),
        _binding(mirror=AvatarMirrorPolicy.CAMERA_HORIZONTAL),
        physical_model(),
    )
    by_id = {value.canonical_joint_id: value for value in command.joint_projections}
    root_projection = by_id["root"]

    assert set(by_id) == {"root", "arm"}
    assert root_projection.renderer_target_ref == "renderer:root"
    assert root_projection.position is not None
    assert root_projection.position.x == pytest.approx(-0.25)
    assert root_projection.position.y == pytest.approx(0.1)
    assert root_projection.rotation is not None
    assert root_projection.rotation.x == pytest.approx(0.0)
    assert root_projection.rotation.y == pytest.approx(-0.0)
    assert root_projection.rotation.z == pytest.approx(-q)
    assert root_projection.rotation.w == pytest.approx(q)


def test_2d_stick_depth_limit_does_not_modify_canonical_frame() -> None:
    binding = _binding(capability=_capability(depth=False))
    frame = _frame(
        1,
        root=JointTransform(Vector3(0.1, 0.2, 0.3), Quaternion(0, 0, 0, 1)),
    )
    command = project_body_pose_frame(frame, binding, physical_model())
    root = next(value for value in command.joint_projections if value.canonical_joint_id == "root")

    assert frame.pose.root_world_transform.position.z == pytest.approx(0.3)
    assert root.position is not None
    assert root.position.z is None
    assert "joint:root:depth_unsupported" in command.degraded_items


def test_canonical_mouth_channel_is_affine_mapped_without_text_input() -> None:
    channel_binding = AvatarChannelBinding(
        RealtimeChannel.MOUTH_OPENNESS,
        "renderer:mouth",
        scale=2.0,
        offset=0.0,
        output_min=0.0,
        output_max=1.0,
    )
    binding = _binding(
        channels=(channel_binding,),
        capability=_capability(
            channels=(RealtimeChannel.MOUTH_OPENNESS,),
        ),
    )
    frame = _frame(
        1,
        channels=(BodyFrameChannelValue(RealtimeChannel.MOUTH_OPENNESS, 0.6),),
    )
    command = project_body_pose_frame(frame, binding, physical_model())

    assert len(command.channel_projections) == 1
    assert command.channel_projections[0].canonical_channel is RealtimeChannel.MOUTH_OPENNESS
    assert command.channel_projections[0].renderer_target_ref == "renderer:mouth"
    assert command.channel_projections[0].value == pytest.approx(1.0)
    forbidden = {"text", "speech_text", "phoneme", "utterance"}
    assert forbidden.isdisjoint({field.name for field in fields(AvatarProjectionCommand)})


def test_latest_frame_coalesces_slow_consumer_without_blocking_submit() -> None:
    renderer = StickAvatarRenderer()
    runtime = AvatarPresentationRuntime(physical_model(), _binding(), renderer)

    runtime.submit_frame(_frame(1))
    runtime.submit_frame(_frame(2))
    runtime.submit_frame(_frame(3))
    assert runtime.pending_frame_count == 1

    report = runtime.present_latest(started_at=NOW)
    assert report is not None
    assert report.status is AvatarProjectionStatus.APPLIED
    assert report.frame_id == "frame:3"
    assert report.dropped_or_coalesced_frames == 2
    assert renderer.latest_command is not None
    assert renderer.latest_command.frame_id == "frame:3"


def test_stale_body_revision_is_dropped_after_successful_projection() -> None:
    renderer = StickAvatarRenderer()
    runtime = AvatarPresentationRuntime(physical_model(), _binding(), renderer)
    runtime.submit_frame(_frame(2))
    first = runtime.present_latest(started_at=NOW)
    assert first is not None and first.status is AvatarProjectionStatus.APPLIED

    runtime.submit_frame(_frame(1, frame_id="frame:old"))
    stale = runtime.present_latest(started_at=NOW + timedelta(seconds=1))
    assert stale is not None
    assert stale.status is AvatarProjectionStatus.DROPPED_STALE
    assert "body_revision_stale" in stale.sanitized_diagnostics


def test_unavailable_renderer_retains_only_latest_frame_for_reconnect() -> None:
    renderer = StickAvatarRenderer(available=False)
    runtime = AvatarPresentationRuntime(physical_model(), _binding(), renderer)
    runtime.submit_frame(_frame(1))

    unavailable = runtime.present_latest(started_at=NOW)
    assert unavailable is not None
    assert unavailable.status is AvatarProjectionStatus.OUTPUT_UNAVAILABLE
    assert runtime.pending_frame_count == 1

    runtime.submit_frame(_frame(2))
    runtime.submit_frame(_frame(3))
    renderer.set_available(True)
    recovered = runtime.present_latest(started_at=NOW + timedelta(seconds=1))

    assert recovered is not None
    assert recovered.status is AvatarProjectionStatus.APPLIED
    assert recovered.frame_id == "frame:3"
    assert renderer.latest_command is not None
    assert renderer.latest_command.frame_id == "frame:3"


def test_reload_requeues_current_latest_frame_under_new_generation() -> None:
    renderer = StickAvatarRenderer()
    runtime = AvatarPresentationRuntime(physical_model(), _binding(generation=1), renderer)
    runtime.submit_frame(_frame(1))
    runtime.reload_binding(_binding(generation=2, revision=2))

    report = runtime.present_latest(started_at=NOW)
    assert report is not None
    assert report.binding_generation == 2
    assert report.binding_revision == 2
    assert renderer.latest_command is not None
    assert renderer.latest_command.binding_generation == 2


class _ReloadingRenderer:
    def __init__(self) -> None:
        self.runtime: AvatarPresentationRuntime | None = None
        self.reloaded = False

    def present(
        self,
        command: AvatarProjectionCommand,
        *,
        started_at: datetime,
    ) -> AvatarRendererResult:
        if not self.reloaded:
            assert self.runtime is not None
            self.runtime.reload_binding(_binding(generation=2, revision=2))
            self.reloaded = True
        return AvatarRendererResult(AvatarRendererStatus.APPLIED, started_at)


def test_in_flight_old_binding_generation_cannot_commit_as_applied() -> None:
    renderer = _ReloadingRenderer()
    runtime = AvatarPresentationRuntime(physical_model(), _binding(generation=1), renderer)
    renderer.runtime = runtime
    runtime.submit_frame(_frame(1))

    stale = runtime.present_latest(started_at=NOW)
    assert stale is not None
    assert stale.status is AvatarProjectionStatus.DROPPED_STALE
    assert "binding_changed_in_flight" in stale.sanitized_diagnostics
    assert runtime.pending_frame_count == 1

    applied = runtime.present_latest(started_at=NOW + timedelta(seconds=1))
    assert applied is not None
    assert applied.status is AvatarProjectionStatus.APPLIED
    assert applied.binding_generation == 2


def test_sample_bindings_share_schema_for_stick_live2d_and_3d() -> None:
    stick = _binding(kind=AvatarModelKind.STICK)
    live2d = replace(
        _binding(kind=AvatarModelKind.LIVE2D),
        model_identity="model:live2d:sample",
    )
    three_d = replace(
        _binding(kind=AvatarModelKind.THREE_D),
        model_identity="model:3d:sample",
    )

    for binding in (stick, live2d, three_d):
        validate_avatar_model_binding(binding, physical_model())
        command = project_body_pose_frame(_frame(1), binding, physical_model())
        assert command.binding_id == binding.binding_id
        assert command.model_identity == binding.model_identity
