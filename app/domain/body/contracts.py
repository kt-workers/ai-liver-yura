from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isclose, isfinite, sqrt
from typing import TypeVar

from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    timestamp_to_json,
    utc_instant,
)


class AnatomicalSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


class AnatomicalRegion(str, Enum):
    ROOT = "root"
    TORSO = "torso"
    HEAD = "head"
    ARM = "arm"
    HAND = "hand"
    LEG = "leg"
    FOOT = "foot"


class Axis(str, Enum):
    X = "X"
    Y = "Y"
    Z = "Z"


def _finite(value: float, field_name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{field_name} は有限の数値でなければなりません")
    return float(value)


def _positive(value: float, field_name: str) -> float:
    result = _finite(value, field_name)
    if result <= 0:
        raise ValueError(f"{field_name} は正でなければなりません")
    return result


T = TypeVar("T")


def _as_tuple(value: tuple[T, ...] | list[T], field_name: str) -> tuple[T, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{field_name} は配列でなければなりません")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class Vector3:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        for field_name in ("x", "y", "z"):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True, slots=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float

    def __post_init__(self) -> None:
        for field_name in ("x", "y", "z", "w"):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))
        magnitude = sqrt(self.x**2 + self.y**2 + self.z**2 + self.w**2)
        if not isclose(magnitude, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("quaternion は単位長でなければなりません")

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}


@dataclass(frozen=True, slots=True)
class JointTransform:
    position: Vector3
    rotation: Quaternion

    def __post_init__(self) -> None:
        if not isinstance(self.position, Vector3):
            raise ValueError("position は Vector3 でなければなりません")
        if not isinstance(self.rotation, Quaternion):
            raise ValueError("rotation は Quaternion でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {"position": self.position.to_dict(), "rotation": self.rotation.to_dict()}


@dataclass(frozen=True, slots=True)
class JointLimit:
    axis: Axis
    hard_min_radians: float
    hard_max_radians: float
    comfortable_min_radians: float
    comfortable_max_radians: float
    relaxed_radians: float

    def __post_init__(self) -> None:
        if not isinstance(self.axis, Axis):
            raise ValueError("axis は Axis でなければなりません")
        for field_name in (
            "hard_min_radians",
            "hard_max_radians",
            "comfortable_min_radians",
            "comfortable_max_radians",
            "relaxed_radians",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))
        if self.hard_min_radians > self.hard_max_radians:
            raise ValueError("hard range の最小値は最大値以下でなければなりません")
        if not (
            self.hard_min_radians
            <= self.comfortable_min_radians
            <= self.comfortable_max_radians
            <= self.hard_max_radians
        ):
            raise ValueError("comfortable range は hard range 内でなければなりません")
        if not self.comfortable_min_radians <= self.relaxed_radians <= self.comfortable_max_radians:
            raise ValueError("relaxed reference は comfortable range 内でなければなりません")

    def to_dict(self) -> dict[str, float | str]:
        return {
            "axis": self.axis.value,
            "hard_min_radians": self.hard_min_radians,
            "hard_max_radians": self.hard_max_radians,
            "comfortable_min_radians": self.comfortable_min_radians,
            "comfortable_max_radians": self.comfortable_max_radians,
            "relaxed_radians": self.relaxed_radians,
        }


@dataclass(frozen=True, slots=True)
class JointDefinition:
    joint_id: str
    parent_joint_id: str | None
    region: AnatomicalRegion
    side: AnatomicalSide
    rest_local_transform: JointTransform
    limits: tuple[JointLimit, ...]

    def __post_init__(self) -> None:
        require_identifier(self.joint_id, "joint_id")
        if self.parent_joint_id is not None:
            require_identifier(self.parent_joint_id, "parent_joint_id")
            if self.parent_joint_id == self.joint_id:
                raise ValueError("joint は自分自身を親にできません")
        if not isinstance(self.region, AnatomicalRegion):
            raise ValueError("region は AnatomicalRegion でなければなりません")
        if not isinstance(self.side, AnatomicalSide):
            raise ValueError("side は AnatomicalSide でなければなりません")
        if not isinstance(self.rest_local_transform, JointTransform):
            raise ValueError("rest_local_transform は JointTransform でなければなりません")
        limits = _as_tuple(self.limits, "limits")
        if any(not isinstance(item, JointLimit) for item in limits):
            raise ValueError("limits は JointLimit の配列でなければなりません")
        if len({item.axis for item in limits}) != len(limits):
            raise ValueError("DOF axis は重複できません")
        object.__setattr__(self, "limits", limits)

    def to_dict(self) -> dict[str, object]:
        return {
            "joint_id": self.joint_id,
            "parent_joint_id": self.parent_joint_id,
            "region": self.region.value,
            "side": self.side.value,
            "rest_local_transform": self.rest_local_transform.to_dict(),
            "limits": [item.to_dict() for item in self.limits],
        }


@dataclass(frozen=True, slots=True)
class SegmentDefinition:
    segment_id: str
    proximal_joint_id: str
    distal_joint_id: str
    normalized_length: float
    mass_fraction: float

    def __post_init__(self) -> None:
        for field_name in ("segment_id", "proximal_joint_id", "distal_joint_id"):
            require_identifier(getattr(self, field_name), field_name)
        if self.proximal_joint_id == self.distal_joint_id:
            raise ValueError("segment の両端jointは異ならなければなりません")
        object.__setattr__(
            self, "normalized_length", _positive(self.normalized_length, "normalized_length")
        )
        object.__setattr__(self, "mass_fraction", _positive(self.mass_fraction, "mass_fraction"))

    def to_dict(self) -> dict[str, str | float]:
        return {
            "segment_id": self.segment_id,
            "proximal_joint_id": self.proximal_joint_id,
            "distal_joint_id": self.distal_joint_id,
            "normalized_length": self.normalized_length,
            "mass_fraction": self.mass_fraction,
        }


@dataclass(frozen=True, slots=True)
class CenterOfMassReference:
    reference_joint_id: str
    local_position: Vector3

    def __post_init__(self) -> None:
        require_identifier(self.reference_joint_id, "reference_joint_id")
        if not isinstance(self.local_position, Vector3):
            raise ValueError("local_position は Vector3 でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_joint_id": self.reference_joint_id,
            "local_position": self.local_position.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class KinematicChain:
    chain_id: str
    joint_ids: tuple[str, ...]
    end_effector_joint_id: str

    def __post_init__(self) -> None:
        require_identifier(self.chain_id, "chain_id")
        joint_ids = _as_tuple(self.joint_ids, "joint_ids")
        if len(joint_ids) < 2:
            raise ValueError("kinematic chain は二つ以上のjointを必要とします")
        for joint_id in joint_ids:
            require_identifier(joint_id, "joint_ids")
        if len(set(joint_ids)) != len(joint_ids):
            raise ValueError("kinematic chain のjointは一意でなければなりません")
        require_identifier(self.end_effector_joint_id, "end_effector_joint_id")
        if self.end_effector_joint_id != joint_ids[-1]:
            raise ValueError("end effector はchainの末端jointでなければなりません")
        object.__setattr__(self, "joint_ids", joint_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "chain_id": self.chain_id,
            "joint_ids": list(self.joint_ids),
            "end_effector_joint_id": self.end_effector_joint_id,
        }


@dataclass(frozen=True, slots=True)
class CanonicalBodyModel:
    body_model_id: str
    joints: tuple[JointDefinition, ...]
    segments: tuple[SegmentDefinition, ...]
    end_effector_joint_ids: tuple[str, ...]
    kinematic_chains: tuple[KinematicChain, ...]
    center_of_mass: CenterOfMassReference
    reference_height: float = 1.0

    def __post_init__(self) -> None:
        require_identifier(self.body_model_id, "body_model_id")
        object.__setattr__(
            self, "reference_height", _positive(self.reference_height, "reference_height")
        )
        joints = _as_tuple(self.joints, "joints")
        segments = _as_tuple(self.segments, "segments")
        end_effectors = _as_tuple(self.end_effector_joint_ids, "end_effector_joint_ids")
        chains = _as_tuple(self.kinematic_chains, "kinematic_chains")
        if not joints or any(not isinstance(item, JointDefinition) for item in joints):
            raise ValueError("joints は空でない JointDefinition の配列でなければなりません")
        if any(not isinstance(item, SegmentDefinition) for item in segments):
            raise ValueError("segments は SegmentDefinition の配列でなければなりません")
        if any(not isinstance(item, KinematicChain) for item in chains):
            raise ValueError("kinematic_chains は KinematicChain の配列でなければなりません")
        if not isinstance(self.center_of_mass, CenterOfMassReference):
            raise ValueError("center_of_mass は CenterOfMassReference でなければなりません")
        joint_ids = {item.joint_id for item in joints}
        if len(joint_ids) != len(joints):
            raise ValueError("joint_id は一意でなければなりません")
        by_id = {item.joint_id: item for item in joints}
        for joint in joints:
            if joint.parent_joint_id is not None and joint.parent_joint_id not in joint_ids:
                raise ValueError("parent_joint_id は既知jointを参照しなければなりません")
        for joint in joints:
            ancestor_ids: set[str] = set()
            current = joint
            while current.parent_joint_id is not None:
                if current.parent_joint_id in ancestor_ids:
                    raise ValueError("skeleton にcycleを含められません")
                ancestor_ids.add(current.parent_joint_id)
                current = by_id[current.parent_joint_id]
        roots = [item for item in joints if item.parent_joint_id is None]
        if len(roots) != 1:
            raise ValueError("skeleton はroot jointを一つだけ持たなければなりません")
        for segment in segments:
            if (
                segment.proximal_joint_id not in joint_ids
                or segment.distal_joint_id not in joint_ids
            ):
                raise ValueError("segment は既知jointを参照しなければなりません")
            if by_id[segment.distal_joint_id].parent_joint_id != segment.proximal_joint_id:
                raise ValueError("segment は直接の親子jointを結ばなければなりません")
        if len({item.segment_id for item in segments}) != len(segments):
            raise ValueError("segment_id は一意でなければなりません")
        if any(item not in joint_ids for item in end_effectors) or len(set(end_effectors)) != len(
            end_effectors
        ):
            raise ValueError("end effector は一意な既知jointでなければなりません")
        for chain in chains:
            if any(joint_id not in joint_ids for joint_id in chain.joint_ids):
                raise ValueError("kinematic chain は既知jointを参照しなければなりません")
            if chain.end_effector_joint_id not in end_effectors:
                raise ValueError("chain の末端はend effectorとして宣言しなければなりません")
            if any(
                by_id[child].parent_joint_id != parent
                for parent, child in zip(chain.joint_ids, chain.joint_ids[1:], strict=False)
            ):
                raise ValueError("kinematic chain は連続した親子joint列でなければなりません")
        if self.center_of_mass.reference_joint_id not in joint_ids:
            raise ValueError("center_of_mass は既知jointを参照しなければなりません")
        object.__setattr__(self, "joints", joints)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "end_effector_joint_ids", end_effectors)
        object.__setattr__(self, "kinematic_chains", chains)

    @property
    def joint_ids(self) -> tuple[str, ...]:
        return tuple(item.joint_id for item in self.joints)

    def to_dict(self) -> dict[str, object]:
        return {
            "body_model_id": self.body_model_id,
            "coordinate_system": {
                "handedness": "right",
                "x": "anatomical_right",
                "y": "up",
                "z": "forward",
            },
            "reference_height": self.reference_height,
            "joints": [item.to_dict() for item in self.joints],
            "segments": [item.to_dict() for item in self.segments],
            "end_effector_joint_ids": list(self.end_effector_joint_ids),
            "kinematic_chains": [item.to_dict() for item in self.kinematic_chains],
            "center_of_mass": self.center_of_mass.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class BodyPose:
    root_world_transform: JointTransform
    joint_local_transforms: tuple[tuple[str, JointTransform], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.root_world_transform, JointTransform):
            raise ValueError("root_world_transform は JointTransform でなければなりません")
        transforms = _as_tuple(self.joint_local_transforms, "joint_local_transforms")
        for joint_id, transform in transforms:
            require_identifier(joint_id, "joint_local_transforms")
            if not isinstance(transform, JointTransform):
                raise ValueError(
                    "joint_local_transforms は JointTransform を持たなければなりません"
                )
        if len({item[0] for item in transforms}) != len(transforms):
            raise ValueError("joint pose のjoint_idは一意でなければなりません")
        object.__setattr__(self, "joint_local_transforms", transforms)

    def validate_for(self, model: CanonicalBodyModel) -> None:
        if not isinstance(model, CanonicalBodyModel):
            raise ValueError("model は CanonicalBodyModel でなければなりません")
        if {item[0] for item in self.joint_local_transforms} != set(model.joint_ids):
            raise ValueError("pose はskeletonの全jointを一度ずつ含まなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "root_world_transform": self.root_world_transform.to_dict(),
            "joint_local_transforms": [
                {"joint_id": joint_id, "transform": transform.to_dict()}
                for joint_id, transform in self.joint_local_transforms
            ],
        }


@dataclass(frozen=True, slots=True)
class JointVelocity:
    linear: Vector3
    angular: Vector3

    def __post_init__(self) -> None:
        if not isinstance(self.linear, Vector3) or not isinstance(self.angular, Vector3):
            raise ValueError("速度は Vector3 でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {"linear": self.linear.to_dict(), "angular": self.angular.to_dict()}


@dataclass(frozen=True, slots=True)
class BodyVelocity:
    root_world_velocity: JointVelocity
    joint_local_velocities: tuple[tuple[str, JointVelocity], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.root_world_velocity, JointVelocity):
            raise ValueError("root_world_velocity は JointVelocity でなければなりません")
        velocities = _as_tuple(self.joint_local_velocities, "joint_local_velocities")
        for joint_id, velocity in velocities:
            require_identifier(joint_id, "joint_local_velocities")
            if not isinstance(velocity, JointVelocity):
                raise ValueError("joint_local_velocities は JointVelocity を持たなければなりません")
        if len({item[0] for item in velocities}) != len(velocities):
            raise ValueError("joint velocity のjoint_idは一意でなければなりません")
        object.__setattr__(self, "joint_local_velocities", velocities)

    def validate_for(self, model: CanonicalBodyModel) -> None:
        if {item[0] for item in self.joint_local_velocities} != set(model.joint_ids):
            raise ValueError("velocity はskeletonの全jointを一度ずつ含まなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "root_world_velocity": self.root_world_velocity.to_dict(),
            "joint_local_velocities": [
                {"joint_id": joint_id, "velocity": velocity.to_dict()}
                for joint_id, velocity in self.joint_local_velocities
            ],
        }


@dataclass(frozen=True, slots=True)
class BodyState:
    body_model_id: str
    revision: int
    observed_at: datetime
    pose: BodyPose
    velocity: BodyVelocity
    history: tuple[tuple[datetime, BodyPose], ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.body_model_id, "body_model_id")
        require_revision(self.revision, "revision")
        require_aware(self.observed_at, "observed_at")
        if not isinstance(self.pose, BodyPose) or not isinstance(self.velocity, BodyVelocity):
            raise ValueError("pose と velocity は正しいBody値でなければなりません")
        history = _as_tuple(self.history, "history")
        for observed_at, pose in history:
            require_aware(observed_at, "history observed_at")
            if not isinstance(pose, BodyPose):
                raise ValueError("history は BodyPose を持たなければなりません")
            if utc_instant(observed_at) > utc_instant(self.observed_at):
                raise ValueError("history はcurrent snapshotより新しくできません")
        object.__setattr__(self, "history", history)

    def validate_for(self, model: CanonicalBodyModel) -> None:
        if self.body_model_id != model.body_model_id:
            raise ValueError("BodyStateのbody_model_idがCanonicalBodyModelと一致しません")
        self.pose.validate_for(model)
        self.velocity.validate_for(model)
        for _, pose in self.history:
            pose.validate_for(model)

    def to_dict(self) -> dict[str, object]:
        return {
            "body_model_id": self.body_model_id,
            "revision": self.revision,
            "observed_at": timestamp_to_json(self.observed_at),
            "pose": self.pose.to_dict(),
            "velocity": self.velocity.to_dict(),
            "history": [
                {"observed_at": timestamp_to_json(observed_at), "pose": pose.to_dict()}
                for observed_at, pose in self.history
            ],
        }
