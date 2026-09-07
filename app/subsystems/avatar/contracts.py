from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.body import Axis
from app.domain.body_realtime import RealtimeChannel
from app.domain.contracts.common import require_aware, require_identifier, require_revision


class AvatarModelKind(str, Enum):
    STICK = "stick"
    LIVE2D = "live2d"
    THREE_D = "3d"


class AvatarMirrorPolicy(str, Enum):
    NONE = "none"
    CAMERA_HORIZONTAL = "camera_horizontal"


class AvatarProjectionStatus(str, Enum):
    APPLIED = "applied"
    PARTIALLY_APPLIED = "partially_applied"
    DROPPED_STALE = "dropped_stale"
    OUTPUT_UNAVAILABLE = "output_unavailable"
    FAILED = "failed"


class AvatarRendererStatus(str, Enum):
    APPLIED = "applied"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


def _identifiers(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name}が不正です")
    for value in values:
        require_identifier(value, name)
    if len(values) != len(set(values)):
        raise ValueError(f"{name}は一意でなければなりません")
    return values


def _axes(values: tuple[Axis, ...], name: str) -> tuple[Axis, ...]:
    if not isinstance(values, tuple) or any(not isinstance(value, Axis) for value in values):
        raise ValueError(f"{name}が不正です")
    if len(values) != len(set(values)):
        raise ValueError(f"{name}は一意でなければなりません")
    return values


def _finite(value: float, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name}は有限値でなければなりません")
    return float(value)


@dataclass(frozen=True, slots=True)
class AvatarCapabilityView:
    supported_joint_ids: tuple[str, ...]
    supported_channels: tuple[RealtimeChannel, ...]
    supported_translation_axes: tuple[Axis, ...]
    supported_rotation_axes: tuple[Axis, ...]
    max_update_rate_hz: float | None
    supports_3d_depth: bool
    supports_root_translation: bool
    supports_face_channels: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "supported_joint_ids",
            _identifiers(self.supported_joint_ids, "supported_joint_ids"),
        )
        channels = tuple(self.supported_channels)
        if any(not isinstance(value, RealtimeChannel) for value in channels):
            raise ValueError("supported_channelsが不正です")
        if len(channels) != len(set(channels)):
            raise ValueError("supported_channelsは一意でなければなりません")
        object.__setattr__(self, "supported_channels", channels)
        object.__setattr__(
            self,
            "supported_translation_axes",
            _axes(self.supported_translation_axes, "supported_translation_axes"),
        )
        object.__setattr__(
            self,
            "supported_rotation_axes",
            _axes(self.supported_rotation_axes, "supported_rotation_axes"),
        )
        if self.max_update_rate_hz is not None:
            rate = _finite(self.max_update_rate_hz, "max_update_rate_hz")
            if rate <= 0:
                raise ValueError("max_update_rate_hzは正でなければなりません")
            object.__setattr__(self, "max_update_rate_hz", rate)
        for name in (
            "supports_3d_depth",
            "supports_root_translation",
            "supports_face_channels",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name}はboolでなければなりません")


@dataclass(frozen=True, slots=True)
class AvatarJointBinding:
    canonical_joint_id: str
    renderer_target_ref: str
    map_position: bool
    map_rotation: bool
    translation_axes: tuple[Axis, ...] = ()
    rotation_axes: tuple[Axis, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.canonical_joint_id, "canonical_joint_id")
        require_identifier(self.renderer_target_ref, "renderer_target_ref")
        if type(self.map_position) is not bool or type(self.map_rotation) is not bool:
            raise ValueError("joint mapping flagが不正です")
        object.__setattr__(
            self,
            "translation_axes",
            _axes(self.translation_axes, "translation_axes"),
        )
        object.__setattr__(self, "rotation_axes", _axes(self.rotation_axes, "rotation_axes"))
        if self.map_position != bool(self.translation_axes):
            raise ValueError("position mappingとtranslation_axesが一致しません")
        if self.map_rotation != bool(self.rotation_axes):
            raise ValueError("rotation mappingとrotation_axesが一致しません")


@dataclass(frozen=True, slots=True)
class AvatarChannelBinding:
    canonical_channel: RealtimeChannel
    renderer_target_ref: str
    scale: float = 1.0
    offset: float = 0.0
    output_min: float = -1.0
    output_max: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_channel, RealtimeChannel):
            raise ValueError("canonical_channelが不正です")
        require_identifier(self.renderer_target_ref, "renderer_target_ref")
        for name in ("scale", "offset", "output_min", "output_max"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.output_min > self.output_max:
            raise ValueError("channel output rangeが不正です")


@dataclass(frozen=True, slots=True)
class AvatarModelBinding:
    binding_id: str
    binding_revision: int
    binding_generation: int
    model_kind: AvatarModelKind
    model_identity: str
    canonical_body_model_id: str
    root_joint_id: str
    joint_bindings: tuple[AvatarJointBinding, ...]
    channel_bindings: tuple[AvatarChannelBinding, ...]
    mirror_policy: AvatarMirrorPolicy
    capability_view: AvatarCapabilityView
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "binding_id",
            "model_identity",
            "canonical_body_model_id",
            "root_joint_id",
        ):
            require_identifier(getattr(self, name), name)
        require_revision(self.binding_revision, "binding_revision")
        require_revision(self.binding_generation, "binding_generation")
        if not isinstance(self.model_kind, AvatarModelKind):
            raise ValueError("model_kindが不正です")
        if not isinstance(self.mirror_policy, AvatarMirrorPolicy):
            raise ValueError("mirror_policyが不正です")
        if not isinstance(self.capability_view, AvatarCapabilityView):
            raise ValueError("capability_viewが不正です")
        joints = tuple(self.joint_bindings)
        channels = tuple(self.channel_bindings)
        if any(not isinstance(value, AvatarJointBinding) for value in joints):
            raise ValueError("joint_bindingsが不正です")
        if any(not isinstance(value, AvatarChannelBinding) for value in channels):
            raise ValueError("channel_bindingsが不正です")
        if len({value.canonical_joint_id for value in joints}) != len(joints):
            raise ValueError("canonical joint bindingは一意でなければなりません")
        if len({value.renderer_target_ref for value in joints}) != len(joints):
            raise ValueError("joint renderer targetは一意でなければなりません")
        if len({value.canonical_channel for value in channels}) != len(channels):
            raise ValueError("canonical channel bindingは一意でなければなりません")
        if len({value.renderer_target_ref for value in channels}) != len(channels):
            raise ValueError("channel renderer targetは一意でなければなりません")
        mapped_joint_ids = {value.canonical_joint_id for value in joints}
        if not mapped_joint_ids.issubset(set(self.capability_view.supported_joint_ids)):
            raise ValueError("joint bindingがcapability外を参照しています")
        mapped_channels = {value.canonical_channel for value in channels}
        if not mapped_channels.issubset(set(self.capability_view.supported_channels)):
            raise ValueError("channel bindingがcapability外を参照しています")
        object.__setattr__(self, "joint_bindings", joints)
        object.__setattr__(self, "channel_bindings", channels)
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class AvatarProjectedVector:
    x: float | None
    y: float | None
    z: float | None

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, name))

    def to_dict(self) -> dict[str, float | None]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True, slots=True)
class AvatarProjectedQuaternion:
    x: float
    y: float
    z: float
    w: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "z", "w"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}


@dataclass(frozen=True, slots=True)
class AvatarJointProjection:
    canonical_joint_id: str
    renderer_target_ref: str
    position: AvatarProjectedVector | None
    rotation: AvatarProjectedQuaternion | None

    def __post_init__(self) -> None:
        require_identifier(self.canonical_joint_id, "canonical_joint_id")
        require_identifier(self.renderer_target_ref, "renderer_target_ref")
        if self.position is not None and not isinstance(self.position, AvatarProjectedVector):
            raise ValueError("position projectionが不正です")
        if self.rotation is not None and not isinstance(
            self.rotation, AvatarProjectedQuaternion
        ):
            raise ValueError("rotation projectionが不正です")
        if self.position is None and self.rotation is None:
            raise ValueError("joint projectionはposition又はrotationが必要です")

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_joint_id": self.canonical_joint_id,
            "renderer_target_ref": self.renderer_target_ref,
            "position": None if self.position is None else self.position.to_dict(),
            "rotation": None if self.rotation is None else self.rotation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AvatarChannelProjection:
    canonical_channel: RealtimeChannel
    renderer_target_ref: str
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_channel, RealtimeChannel):
            raise ValueError("canonical_channelが不正です")
        require_identifier(self.renderer_target_ref, "renderer_target_ref")
        object.__setattr__(self, "value", _finite(self.value, "value"))

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_channel": self.canonical_channel.value,
            "renderer_target_ref": self.renderer_target_ref,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class AvatarProjectionCommand:
    frame_id: str
    body_state_revision: int
    observed_at: datetime
    binding_id: str
    binding_revision: int
    binding_generation: int
    model_identity: str
    joint_projections: tuple[AvatarJointProjection, ...]
    channel_projections: tuple[AvatarChannelProjection, ...]
    degraded_items: tuple[str, ...]
    trace_id: str

    def __post_init__(self) -> None:
        for name in ("frame_id", "binding_id", "model_identity", "trace_id"):
            require_identifier(getattr(self, name), name)
        for name in ("body_state_revision", "binding_revision", "binding_generation"):
            require_revision(getattr(self, name), name)
        require_aware(self.observed_at, "observed_at")
        joints = tuple(self.joint_projections)
        channels = tuple(self.channel_projections)
        if any(not isinstance(value, AvatarJointProjection) for value in joints):
            raise ValueError("joint_projectionsが不正です")
        if any(not isinstance(value, AvatarChannelProjection) for value in channels):
            raise ValueError("channel_projectionsが不正です")
        if len({value.canonical_joint_id for value in joints}) != len(joints):
            raise ValueError("joint_projectionsが重複しています")
        if len({value.canonical_channel for value in channels}) != len(channels):
            raise ValueError("channel_projectionsが重複しています")
        object.__setattr__(self, "joint_projections", joints)
        object.__setattr__(self, "channel_projections", channels)
        object.__setattr__(
            self,
            "degraded_items",
            _identifiers(tuple(self.degraded_items), "degraded_items"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_id": self.frame_id,
            "body_state_revision": self.body_state_revision,
            "observed_at": self.observed_at.isoformat(),
            "binding_id": self.binding_id,
            "binding_revision": self.binding_revision,
            "binding_generation": self.binding_generation,
            "model_identity": self.model_identity,
            "joint_projections": [value.to_dict() for value in self.joint_projections],
            "channel_projections": [value.to_dict() for value in self.channel_projections],
            "degraded_items": list(self.degraded_items),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class AvatarRendererResult:
    status: AvatarRendererStatus
    completed_at: datetime
    sanitized_diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, AvatarRendererStatus):
            raise ValueError("renderer statusが不正です")
        require_aware(self.completed_at, "completed_at")
        object.__setattr__(
            self,
            "sanitized_diagnostics",
            _identifiers(tuple(self.sanitized_diagnostics), "sanitized_diagnostics"),
        )


@dataclass(frozen=True, slots=True)
class AvatarProjectionReport:
    frame_id: str
    binding_id: str
    binding_revision: int
    binding_generation: int
    model_identity: str
    status: AvatarProjectionStatus
    applied_joint_ids: tuple[str, ...]
    applied_channels: tuple[RealtimeChannel, ...]
    degraded_items: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    dropped_or_coalesced_frames: int
    sanitized_diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("frame_id", "binding_id", "model_identity"):
            require_identifier(getattr(self, name), name)
        require_revision(self.binding_revision, "binding_revision")
        require_revision(self.binding_generation, "binding_generation")
        if not isinstance(self.status, AvatarProjectionStatus):
            raise ValueError("projection statusが不正です")
        object.__setattr__(
            self,
            "applied_joint_ids",
            _identifiers(tuple(self.applied_joint_ids), "applied_joint_ids"),
        )
        channels = tuple(self.applied_channels)
        if any(not isinstance(value, RealtimeChannel) for value in channels):
            raise ValueError("applied_channelsが不正です")
        if len(channels) != len(set(channels)):
            raise ValueError("applied_channelsが重複しています")
        object.__setattr__(self, "applied_channels", channels)
        object.__setattr__(
            self,
            "degraded_items",
            _identifiers(tuple(self.degraded_items), "degraded_items"),
        )
        object.__setattr__(
            self,
            "sanitized_diagnostics",
            _identifiers(tuple(self.sanitized_diagnostics), "sanitized_diagnostics"),
        )
        require_aware(self.started_at, "started_at")
        require_aware(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise ValueError("projection report timeが逆転しています")
        if (
            type(self.dropped_or_coalesced_frames) is not int
            or self.dropped_or_coalesced_frames < 0
        ):
            raise ValueError("dropped_or_coalesced_framesが不正です")
