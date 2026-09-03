from __future__ import annotations

from app.domain.body import Axis, CanonicalBodyModel, JointTransform
from app.domain.body_realtime import RealtimeChannel
from app.domain.body_solver import BodyPoseFrame

from .contracts import (
    AvatarChannelBinding,
    AvatarChannelProjection,
    AvatarJointBinding,
    AvatarJointProjection,
    AvatarMirrorPolicy,
    AvatarModelBinding,
    AvatarProjectedQuaternion,
    AvatarProjectedVector,
    AvatarProjectionCommand,
)

_ALL_AXES = frozenset({Axis.X, Axis.Y, Axis.Z})
_FACE_CHANNELS = frozenset(
    {
        RealtimeChannel.EYELID_OPENNESS,
        RealtimeChannel.MOUTH_OPENNESS,
        RealtimeChannel.MOUTH_ROUNDNESS,
        RealtimeChannel.JAW_OPENNESS,
        RealtimeChannel.LIP_CLOSURE,
    }
)


def validate_avatar_model_binding(
    binding: AvatarModelBinding,
    model: CanonicalBodyModel,
) -> None:
    if not isinstance(binding, AvatarModelBinding):
        raise ValueError("bindingが不正です")
    if not isinstance(model, CanonicalBodyModel):
        raise ValueError("modelが不正です")
    if binding.canonical_body_model_id != model.body_model_id:
        raise ValueError("bindingのCanonical Body Modelが一致しません")
    if binding.root_joint_id != model.root_joint_id:
        raise ValueError("bindingのroot jointが一致しません")
    model_joint_ids = set(model.joint_ids)
    capability_joint_ids = set(binding.capability_view.supported_joint_ids)
    if not capability_joint_ids.issubset(model_joint_ids):
        raise ValueError("Avatar capabilityが未知Canonical jointを参照しています")
    if any(value.canonical_joint_id not in model_joint_ids for value in binding.joint_bindings):
        raise ValueError("Avatar bindingが未知Canonical jointを参照しています")
    capability_translation_axes = set(binding.capability_view.supported_translation_axes)
    capability_rotation_axes = set(binding.capability_view.supported_rotation_axes)
    for value in binding.joint_bindings:
        if not set(value.translation_axes).issubset(capability_translation_axes):
            raise ValueError("joint translation mappingがcapability外です")
        if not set(value.rotation_axes).issubset(capability_rotation_axes):
            raise ValueError("joint rotation mappingがcapability外です")


def project_body_pose_frame(
    frame: BodyPoseFrame,
    binding: AvatarModelBinding,
    model: CanonicalBodyModel,
) -> AvatarProjectionCommand:
    if not isinstance(frame, BodyPoseFrame):
        raise ValueError("frameが不正です")
    validate_avatar_model_binding(binding, model)
    if frame.body_model_id != model.body_model_id:
        raise ValueError("frameのCanonical Body Modelが一致しません")
    frame.pose.validate_for(model)

    joint_bindings = {value.canonical_joint_id: value for value in binding.joint_bindings}
    local_transforms = dict(frame.pose.joint_local_transforms)
    joint_projections: list[AvatarJointProjection] = []
    channel_projections: list[AvatarChannelProjection] = []
    degraded: set[str] = set()

    for joint_id in model.joint_ids:
        joint_mapping = joint_bindings.get(joint_id)
        if joint_mapping is None:
            degraded.add(f"joint:{joint_id}:unmapped")
            continue
        transform = (
            frame.pose.root_world_transform
            if joint_id == model.root_joint_id
            else local_transforms[joint_id]
        )
        projection = _project_joint(
            joint_id,
            transform,
            joint_mapping,
            binding,
            degraded,
        )
        if projection is not None:
            joint_projections.append(projection)

    channel_bindings = {
        value.canonical_channel: value for value in binding.channel_bindings
    }
    supported_channels = set(binding.capability_view.supported_channels)
    for channel_value in frame.channel_values:
        channel = channel_value.channel
        channel_mapping = channel_bindings.get(channel)
        if channel_mapping is None or channel not in supported_channels:
            degraded.add(f"channel:{channel.value}:unmapped")
            continue
        if channel in _FACE_CHANNELS and not binding.capability_view.supports_face_channels:
            degraded.add(f"channel:{channel.value}:face_unsupported")
            continue
        channel_projections.append(
            AvatarChannelProjection(
                channel,
                channel_mapping.renderer_target_ref,
                _project_channel_value(channel_value.value, channel_mapping),
            )
        )

    return AvatarProjectionCommand(
        frame.frame_id,
        frame.body_state_revision,
        frame.observed_at,
        binding.binding_id,
        binding.binding_revision,
        binding.binding_generation,
        binding.model_identity,
        tuple(joint_projections),
        tuple(channel_projections),
        tuple(sorted(degraded)),
        frame.trace_id,
    )


def _project_joint(
    joint_id: str,
    transform: JointTransform,
    mapping: AvatarJointBinding,
    binding: AvatarModelBinding,
    degraded: set[str],
) -> AvatarJointProjection | None:
    position = _project_position(joint_id, transform, mapping, binding, degraded)
    rotation = _project_rotation(joint_id, transform, mapping, binding, degraded)
    if position is None and rotation is None:
        degraded.add(f"joint:{joint_id}:not_projected")
        return None
    return AvatarJointProjection(
        joint_id,
        mapping.renderer_target_ref,
        position,
        rotation,
    )


def _project_position(
    joint_id: str,
    transform: JointTransform,
    mapping: AvatarJointBinding,
    binding: AvatarModelBinding,
    degraded: set[str],
) -> AvatarProjectedVector | None:
    if not mapping.map_position:
        degraded.add(f"joint:{joint_id}:position_unmapped")
        return None
    if (
        joint_id == binding.root_joint_id
        and not binding.capability_view.supports_root_translation
    ):
        degraded.add(f"joint:{joint_id}:root_translation_unsupported")
        return None

    mapping_axes = set(mapping.translation_axes)
    capability_axes = set(binding.capability_view.supported_translation_axes)
    values = {
        Axis.X: transform.position.x,
        Axis.Y: transform.position.y,
        Axis.Z: transform.position.z,
    }
    projected: dict[Axis, float | None] = {}
    for axis in (Axis.X, Axis.Y, Axis.Z):
        if axis not in mapping_axes or axis not in capability_axes:
            projected[axis] = None
            degraded.add(f"joint:{joint_id}:translation_{axis.value.lower()}_unsupported")
            continue
        if axis is Axis.Z and not binding.capability_view.supports_3d_depth:
            projected[axis] = None
            degraded.add(f"joint:{joint_id}:depth_unsupported")
            continue
        projected[axis] = values[axis]

    if all(value is None for value in projected.values()):
        return None
    x = projected[Axis.X]
    if x is not None and binding.mirror_policy is AvatarMirrorPolicy.CAMERA_HORIZONTAL:
        x = -x
    return AvatarProjectedVector(x, projected[Axis.Y], projected[Axis.Z])


def _project_rotation(
    joint_id: str,
    transform: JointTransform,
    mapping: AvatarJointBinding,
    binding: AvatarModelBinding,
    degraded: set[str],
) -> AvatarProjectedQuaternion | None:
    if not mapping.map_rotation:
        degraded.add(f"joint:{joint_id}:rotation_unmapped")
        return None
    if set(mapping.rotation_axes) != _ALL_AXES:
        degraded.add(f"joint:{joint_id}:partial_rotation_unsupported")
        return None
    if not _ALL_AXES.issubset(set(binding.capability_view.supported_rotation_axes)):
        degraded.add(f"joint:{joint_id}:rotation_capability_unsupported")
        return None
    rotation = transform.rotation
    if binding.mirror_policy is AvatarMirrorPolicy.CAMERA_HORIZONTAL:
        return AvatarProjectedQuaternion(rotation.x, -rotation.y, -rotation.z, rotation.w)
    return AvatarProjectedQuaternion(rotation.x, rotation.y, rotation.z, rotation.w)


def _project_channel_value(value: float, mapping: AvatarChannelBinding) -> float:
    projected = value * mapping.scale + mapping.offset
    return min(mapping.output_max, max(mapping.output_min, projected))
