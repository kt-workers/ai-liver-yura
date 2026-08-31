from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import cos, isclose, isfinite, sin, sqrt
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


def _unit_interval(value: float, field_name: str) -> float:
    result = _finite(value, field_name)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field_name} は [0, 1] でなければなりません")
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

    @property
    def magnitude(self) -> float:
        return sqrt(self.x**2 + self.y**2 + self.z**2)

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


def _multiply_quaternion(left: Quaternion, right: Quaternion) -> Quaternion:
    return Quaternion(
        left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y,
        left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x,
        left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w,
        left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z,
    )


def _axis_quaternion(axis: Axis, radians: float) -> Quaternion:
    half = _finite(radians, "radians") / 2.0
    value = sin(half)
    scalar = cos(half)
    if axis is Axis.X:
        return Quaternion(value, 0.0, 0.0, scalar)
    if axis is Axis.Y:
        return Quaternion(0.0, value, 0.0, scalar)
    return Quaternion(0.0, 0.0, value, scalar)


def quaternion_equivalent(
    left: Quaternion,
    right: Quaternion,
    *,
    absolute_tolerance: float = 1e-6,
) -> bool:
    tolerance = _positive(absolute_tolerance, "absolute_tolerance")
    direct = max(
        abs(left.x - right.x),
        abs(left.y - right.y),
        abs(left.z - right.z),
        abs(left.w - right.w),
    )
    negated = max(
        abs(left.x + right.x),
        abs(left.y + right.y),
        abs(left.z + right.z),
        abs(left.w + right.w),
    )
    return min(direct, negated) <= tolerance


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
class JointDynamicLimit:
    axis: Axis
    max_velocity_radians_per_second: float
    max_acceleration_radians_per_second2: float
    max_jerk_radians_per_second3: float

    def __post_init__(self) -> None:
        if not isinstance(self.axis, Axis):
            raise ValueError("axis は Axis でなければなりません")
        for field_name in (
            "max_velocity_radians_per_second",
            "max_acceleration_radians_per_second2",
            "max_jerk_radians_per_second3",
        ):
            object.__setattr__(self, field_name, _positive(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, float | str]:
        return {
            "axis": self.axis.value,
            "max_velocity_radians_per_second": self.max_velocity_radians_per_second,
            "max_acceleration_radians_per_second2": self.max_acceleration_radians_per_second2,
            "max_jerk_radians_per_second3": self.max_jerk_radians_per_second3,
        }


@dataclass(frozen=True, slots=True)
class RootDynamicLimit:
    max_linear_velocity_mps: float
    max_linear_acceleration_mps2: float
    max_linear_jerk_mps3: float
    max_angular_velocity_radps: float
    max_angular_acceleration_radps2: float
    max_angular_jerk_radps3: float
    directional_translation_budget_m: float
    impulse_budget_mps: float

    def __post_init__(self) -> None:
        for field_name in (
            "max_linear_velocity_mps",
            "max_linear_acceleration_mps2",
            "max_linear_jerk_mps3",
            "max_angular_velocity_radps",
            "max_angular_acceleration_radps2",
            "max_angular_jerk_radps3",
            "directional_translation_budget_m",
            "impulse_budget_mps",
        ):
            object.__setattr__(self, field_name, _positive(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, float]:
        return {
            "max_linear_velocity_mps": self.max_linear_velocity_mps,
            "max_linear_acceleration_mps2": self.max_linear_acceleration_mps2,
            "max_linear_jerk_mps3": self.max_linear_jerk_mps3,
            "max_angular_velocity_radps": self.max_angular_velocity_radps,
            "max_angular_acceleration_radps2": self.max_angular_acceleration_radps2,
            "max_angular_jerk_radps3": self.max_angular_jerk_radps3,
            "directional_translation_budget_m": self.directional_translation_budget_m,
            "impulse_budget_mps": self.impulse_budget_mps,
        }


@dataclass(frozen=True, slots=True)
class JointDofCoordinate:
    axis: Axis
    position_radians: float
    velocity_radians_per_second: float
    acceleration_radians_per_second2: float

    def __post_init__(self) -> None:
        if not isinstance(self.axis, Axis):
            raise ValueError("axis は Axis でなければなりません")
        for field_name in (
            "position_radians",
            "velocity_radians_per_second",
            "acceleration_radians_per_second2",
        ):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, float | str]:
        return {
            "axis": self.axis.value,
            "position_radians": self.position_radians,
            "velocity_radians_per_second": self.velocity_radians_per_second,
            "acceleration_radians_per_second2": self.acceleration_radians_per_second2,
        }


@dataclass(frozen=True, slots=True)
class JointDofState:
    joint_id: str
    coordinates: tuple[JointDofCoordinate, ...]

    def __post_init__(self) -> None:
        require_identifier(self.joint_id, "joint_id")
        coordinates = _as_tuple(self.coordinates, "coordinates")
        if any(not isinstance(item, JointDofCoordinate) for item in coordinates):
            raise ValueError("coordinates は JointDofCoordinate の配列でなければなりません")
        if len({item.axis for item in coordinates}) != len(coordinates):
            raise ValueError("DOF coordinate axis は重複できません")
        object.__setattr__(
            self,
            "coordinates",
            tuple(sorted(coordinates, key=lambda item: item.axis.value)),
        )

    def validate_for(self, joint: JointDefinition) -> None:
        if self.joint_id != joint.joint_id:
            raise ValueError("JointDofStateのjoint_idがJointDefinitionと一致しません")
        limits = {item.axis: item for item in joint.limits}
        coordinates = {item.axis: item for item in self.coordinates}
        if set(coordinates) != set(limits):
            raise ValueError("JointDofStateは宣言済みDOF axisをexactly once持つ必要があります")
        for axis, coordinate in coordinates.items():
            limit = limits[axis]
            if not limit.hard_min_radians <= coordinate.position_radians <= limit.hard_max_radians:
                raise ValueError("JointDofState positionがhard limit外です")

    def to_dict(self) -> dict[str, object]:
        return {
            "joint_id": self.joint_id,
            "coordinates": [item.to_dict() for item in self.coordinates],
        }


@dataclass(frozen=True, slots=True)
class JointDefinition:
    joint_id: str
    parent_joint_id: str | None
    region: AnatomicalRegion
    side: AnatomicalSide
    rest_local_transform: JointTransform
    limits: tuple[JointLimit, ...]
    dynamic_limits: tuple[JointDynamicLimit, ...] = ()

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
        dynamic_limits = _as_tuple(self.dynamic_limits, "dynamic_limits")
        if any(not isinstance(item, JointDynamicLimit) for item in dynamic_limits):
            raise ValueError("dynamic_limits は JointDynamicLimit の配列でなければなりません")
        if len({item.axis for item in dynamic_limits}) != len(dynamic_limits):
            raise ValueError("dynamic limit axis は重複できません")
        if not {item.axis for item in dynamic_limits}.issubset({item.axis for item in limits}):
            raise ValueError("dynamic limit axisは宣言済みDOF axisだけを参照できます")
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "dynamic_limits", dynamic_limits)

    @property
    def physical_dynamics_complete(self) -> bool:
        return {item.axis for item in self.dynamic_limits} == {item.axis for item in self.limits}

    def to_dict(self) -> dict[str, object]:
        return {
            "joint_id": self.joint_id,
            "parent_joint_id": self.parent_joint_id,
            "region": self.region.value,
            "side": self.side.value,
            "rest_local_transform": self.rest_local_transform.to_dict(),
            "limits": [item.to_dict() for item in self.limits],
            "dynamic_limits": [item.to_dict() for item in self.dynamic_limits],
        }


@dataclass(frozen=True, slots=True)
class SegmentDefinition:
    segment_id: str
    proximal_joint_id: str
    distal_joint_id: str
    normalized_length: float
    mass_fraction: float
    center_of_mass_fraction_from_proximal: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("segment_id", "proximal_joint_id", "distal_joint_id"):
            require_identifier(getattr(self, field_name), field_name)
        if self.proximal_joint_id == self.distal_joint_id:
            raise ValueError("segment の両端jointは異ならなければなりません")
        object.__setattr__(
            self, "normalized_length", _positive(self.normalized_length, "normalized_length")
        )
        object.__setattr__(self, "mass_fraction", _positive(self.mass_fraction, "mass_fraction"))
        if self.center_of_mass_fraction_from_proximal is not None:
            object.__setattr__(
                self,
                "center_of_mass_fraction_from_proximal",
                _unit_interval(
                    self.center_of_mass_fraction_from_proximal,
                    "center_of_mass_fraction_from_proximal",
                ),
            )

    def to_dict(self) -> dict[str, str | float | None]:
        return {
            "segment_id": self.segment_id,
            "proximal_joint_id": self.proximal_joint_id,
            "distal_joint_id": self.distal_joint_id,
            "normalized_length": self.normalized_length,
            "mass_fraction": self.mass_fraction,
            "center_of_mass_fraction_from_proximal": self.center_of_mass_fraction_from_proximal,
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


def _require_unit_vector(value: Vector3, field_name: str) -> None:
    if not isinstance(value, Vector3):
        raise ValueError(f"{field_name} は Vector3 でなければなりません")
    if not isclose(value.magnitude, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(f"{field_name} は単位Vector3でなければなりません")


@dataclass(frozen=True, slots=True)
class EndEffectorDefinition:
    end_effector_id: str
    joint_id: str
    local_position: Vector3
    local_forward_axis: Vector3
    local_up_axis: Vector3

    def __post_init__(self) -> None:
        require_identifier(self.end_effector_id, "end_effector_id")
        require_identifier(self.joint_id, "joint_id")
        if not isinstance(self.local_position, Vector3):
            raise ValueError("local_position は Vector3 でなければなりません")
        _require_unit_vector(self.local_forward_axis, "local_forward_axis")
        _require_unit_vector(self.local_up_axis, "local_up_axis")
        dot = (
            self.local_forward_axis.x * self.local_up_axis.x
            + self.local_forward_axis.y * self.local_up_axis.y
            + self.local_forward_axis.z * self.local_up_axis.z
        )
        if isclose(abs(dot), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("end effector forward/up axis は平行にできません")

    def to_dict(self) -> dict[str, object]:
        return {
            "end_effector_id": self.end_effector_id,
            "joint_id": self.joint_id,
            "local_position": self.local_position.to_dict(),
            "local_forward_axis": self.local_forward_axis.to_dict(),
            "local_up_axis": self.local_up_axis.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ContactPointDefinition:
    contact_id: str
    joint_id: str
    local_position: Vector3
    support_capable: bool

    def __post_init__(self) -> None:
        require_identifier(self.contact_id, "contact_id")
        require_identifier(self.joint_id, "joint_id")
        if not isinstance(self.local_position, Vector3):
            raise ValueError("local_position は Vector3 でなければなりません")
        if type(self.support_capable) is not bool:
            raise ValueError("support_capable は bool でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "contact_id": self.contact_id,
            "joint_id": self.joint_id,
            "local_position": self.local_position.to_dict(),
            "support_capable": self.support_capable,
        }


@dataclass(frozen=True, slots=True)
class KinematicChain:
    chain_id: str
    joint_ids: tuple[str, ...]
    end_effector_joint_id: str
    end_effector_id: str | None = None

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
        if self.end_effector_id is not None:
            require_identifier(self.end_effector_id, "end_effector_id")
        object.__setattr__(self, "joint_ids", joint_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "chain_id": self.chain_id,
            "joint_ids": list(self.joint_ids),
            "end_effector_joint_id": self.end_effector_joint_id,
            "end_effector_id": self.end_effector_id,
        }


def project_joint_dof_rotation(joint: JointDefinition, state: JointDofState) -> Quaternion:
    if not isinstance(joint, JointDefinition):
        raise ValueError("joint は JointDefinition でなければなりません")
    if not isinstance(state, JointDofState):
        raise ValueError("state は JointDofState でなければなりません")
    state.validate_for(joint)
    coordinates = {item.axis: item.position_radians for item in state.coordinates}
    rotation = joint.rest_local_transform.rotation
    for axis in (Axis.X, Axis.Y, Axis.Z):
        if axis in coordinates:
            rotation = _multiply_quaternion(rotation, _axis_quaternion(axis, coordinates[axis]))
    return rotation


@dataclass(frozen=True, slots=True)
class CanonicalBodyModel:
    body_model_id: str
    joints: tuple[JointDefinition, ...]
    segments: tuple[SegmentDefinition, ...]
    end_effector_joint_ids: tuple[str, ...]
    kinematic_chains: tuple[KinematicChain, ...]
    center_of_mass: CenterOfMassReference
    reference_height: float = 1.0
    body_model_revision: int = 0
    body_model_fingerprint: str | None = None
    end_effectors: tuple[EndEffectorDefinition, ...] = ()
    contact_points: tuple[ContactPointDefinition, ...] = ()
    root_dynamic_limit: RootDynamicLimit | None = None

    def __post_init__(self) -> None:
        require_identifier(self.body_model_id, "body_model_id")
        require_revision(self.body_model_revision, "body_model_revision")
        object.__setattr__(
            self, "reference_height", _positive(self.reference_height, "reference_height")
        )
        joints = _as_tuple(self.joints, "joints")
        segments = _as_tuple(self.segments, "segments")
        end_effectors_legacy = _as_tuple(self.end_effector_joint_ids, "end_effector_joint_ids")
        chains = _as_tuple(self.kinematic_chains, "kinematic_chains")
        end_effectors = _as_tuple(self.end_effectors, "end_effectors")
        contact_points = _as_tuple(self.contact_points, "contact_points")
        if not joints or any(not isinstance(item, JointDefinition) for item in joints):
            raise ValueError("joints は空でない JointDefinition の配列でなければなりません")
        if any(not isinstance(item, SegmentDefinition) for item in segments):
            raise ValueError("segments は SegmentDefinition の配列でなければなりません")
        if any(not isinstance(item, KinematicChain) for item in chains):
            raise ValueError("kinematic_chains は KinematicChain の配列でなければなりません")
        if any(not isinstance(item, EndEffectorDefinition) for item in end_effectors):
            raise ValueError("end_effectors は EndEffectorDefinition の配列でなければなりません")
        if any(not isinstance(item, ContactPointDefinition) for item in contact_points):
            raise ValueError("contact_points は ContactPointDefinition の配列でなければなりません")
        if self.root_dynamic_limit is not None and not isinstance(
            self.root_dynamic_limit, RootDynamicLimit
        ):
            raise ValueError("root_dynamic_limit は RootDynamicLimit でなければなりません")
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
        if any(item not in joint_ids for item in end_effectors_legacy) or len(
            set(end_effectors_legacy)
        ) != len(end_effectors_legacy):
            raise ValueError("end effector は一意な既知jointでなければなりません")
        if len({item.end_effector_id for item in end_effectors}) != len(end_effectors):
            raise ValueError("end_effector_id は一意でなければなりません")
        if len({item.joint_id for item in end_effectors}) != len(end_effectors):
            raise ValueError("end effector joint binding は一意でなければなりません")
        if any(item.joint_id not in joint_ids for item in end_effectors):
            raise ValueError("end effector definition は既知jointを参照しなければなりません")
        if end_effectors and {item.joint_id for item in end_effectors} != set(
            end_effectors_legacy
        ):
            raise ValueError("end effector definition はlegacy joint宣言と一致しなければなりません")
        end_effector_by_id = {item.end_effector_id: item for item in end_effectors}
        for chain in chains:
            if any(joint_id not in joint_ids for joint_id in chain.joint_ids):
                raise ValueError("kinematic chain は既知jointを参照しなければなりません")
            if chain.end_effector_joint_id not in end_effectors_legacy:
                raise ValueError("chain の末端はend effectorとして宣言しなければなりません")
            if any(
                by_id[child].parent_joint_id != parent
                for parent, child in zip(chain.joint_ids, chain.joint_ids[1:], strict=False)
            ):
                raise ValueError("kinematic chain は連続した親子joint列でなければなりません")
            if chain.end_effector_id is not None:
                definition = end_effector_by_id.get(chain.end_effector_id)
                if definition is None or definition.joint_id != chain.end_effector_joint_id:
                    raise ValueError("chainのend_effector_id bindingが不正です")
        if len({item.contact_id for item in contact_points}) != len(contact_points):
            raise ValueError("contact_id は一意でなければなりません")
        if any(item.joint_id not in joint_ids for item in contact_points):
            raise ValueError("contact point は既知jointを参照しなければなりません")
        if self.center_of_mass.reference_joint_id not in joint_ids:
            raise ValueError("center_of_mass は既知jointを参照しなければなりません")
        object.__setattr__(self, "joints", joints)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "end_effector_joint_ids", end_effectors_legacy)
        object.__setattr__(self, "kinematic_chains", chains)
        object.__setattr__(self, "end_effectors", end_effectors)
        object.__setattr__(self, "contact_points", contact_points)

        calculated = self._calculate_fingerprint()
        if self.body_model_fingerprint is None:
            object.__setattr__(self, "body_model_fingerprint", calculated)
        else:
            require_identifier(self.body_model_fingerprint, "body_model_fingerprint")

    def _calculate_fingerprint(self) -> str:
        payload = {
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
            "end_effectors": [item.to_dict() for item in self.end_effectors],
            "kinematic_chains": [item.to_dict() for item in self.kinematic_chains],
            "contact_points": [item.to_dict() for item in self.contact_points],
            "center_of_mass": self.center_of_mass.to_dict(),
            "root_dynamic_limit": (
                None if self.root_dynamic_limit is None else self.root_dynamic_limit.to_dict()
            ),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def joint_ids(self) -> tuple[str, ...]:
        return tuple(item.joint_id for item in self.joints)

    @property
    def root_joint_id(self) -> str:
        return next(item.joint_id for item in self.joints if item.parent_joint_id is None)

    @property
    def physical_control_contract_complete(self) -> bool:
        fingerprint_matches = self.body_model_fingerprint == self._calculate_fingerprint()
        mass_fraction_complete = not self.segments or isclose(
            sum(item.mass_fraction for item in self.segments),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        return (
            fingerprint_matches
            and mass_fraction_complete
            and all(item.physical_dynamics_complete for item in self.joints)
            and all(
                item.center_of_mass_fraction_from_proximal is not None for item in self.segments
            )
            and bool(self.end_effectors)
            and all(item.end_effector_id is not None for item in self.kinematic_chains)
            and self.root_dynamic_limit is not None
        )

    def require_physical_control_contract(self) -> None:
        if not self.physical_control_contract_complete:
            raise ValueError("CanonicalBodyModelのphysical control contractが不完全です")

    def to_dict(self) -> dict[str, object]:
        return {
            "body_model_id": self.body_model_id,
            "body_model_revision": self.body_model_revision,
            "body_model_fingerprint": self.body_model_fingerprint,
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
            "end_effectors": [item.to_dict() for item in self.end_effectors],
            "kinematic_chains": [item.to_dict() for item in self.kinematic_chains],
            "contact_points": [item.to_dict() for item in self.contact_points],
            "center_of_mass": self.center_of_mass.to_dict(),
            "root_dynamic_limit": (
                None if self.root_dynamic_limit is None else self.root_dynamic_limit.to_dict()
            ),
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
        if {item[0] for item in self.joint_local_transforms} != {
            joint_id for joint_id in model.joint_ids if joint_id != model.root_joint_id
        }:
            raise ValueError("pose はroot以外の全jointを一度ずつ含まなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "root_world_transform": self.root_world_transform.to_dict(),
            "joint_local_transforms": [
                {"joint_id": joint_id, "transform": transform.to_dict()}
                for joint_id, transform in self.joint_local_transforms
            ],
        }


def project_body_pose_from_dof(
    model: CanonicalBodyModel,
    root_world_transform: JointTransform,
    joint_dof_states: tuple[JointDofState, ...],
) -> BodyPose:
    if not isinstance(model, CanonicalBodyModel):
        raise ValueError("model は CanonicalBodyModel でなければなりません")
    if not isinstance(root_world_transform, JointTransform):
        raise ValueError("root_world_transform は JointTransform でなければなりません")
    states = _as_tuple(joint_dof_states, "joint_dof_states")
    if any(not isinstance(item, JointDofState) for item in states):
        raise ValueError("joint_dof_states は JointDofState の配列でなければなりません")
    by_id = {item.joint_id: item for item in states}
    required_ids = {item.joint_id for item in model.joints if item.limits}
    if set(by_id) != required_ids:
        raise ValueError("joint_dof_statesはDOFを持つ全jointをexactly once含む必要があります")
    result: list[tuple[str, JointTransform]] = []
    for joint in model.joints:
        if joint.joint_id == model.root_joint_id:
            continue
        rotation = joint.rest_local_transform.rotation
        if joint.limits:
            rotation = project_joint_dof_rotation(joint, by_id[joint.joint_id])
        result.append(
            (
                joint.joint_id,
                JointTransform(joint.rest_local_transform.position, rotation),
            )
        )
    return BodyPose(root_world_transform, tuple(result))


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
        if {item[0] for item in self.joint_local_velocities} != {
            joint_id for joint_id in model.joint_ids if joint_id != model.root_joint_id
        }:
            raise ValueError("velocity はroot以外の全jointを一度ずつ含まなければなりません")

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
    body_model_revision: int | None = None
    body_model_fingerprint: str | None = None
    joint_dof_states: tuple[JointDofState, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.body_model_id, "body_model_id")
        require_revision(self.revision, "revision")
        require_aware(self.observed_at, "observed_at")
        if self.body_model_revision is not None:
            require_revision(self.body_model_revision, "body_model_revision")
        if self.body_model_fingerprint is not None:
            require_identifier(self.body_model_fingerprint, "body_model_fingerprint")
        if not isinstance(self.pose, BodyPose) or not isinstance(self.velocity, BodyVelocity):
            raise ValueError("pose と velocity は正しいBody値でなければなりません")
        history = _as_tuple(self.history, "history")
        for observed_at, pose in history:
            require_aware(observed_at, "history observed_at")
            if not isinstance(pose, BodyPose):
                raise ValueError("history は BodyPose を持たなければなりません")
            if utc_instant(observed_at) > utc_instant(self.observed_at):
                raise ValueError("history はcurrent snapshotより新しくできません")
        joint_dof_states = _as_tuple(self.joint_dof_states, "joint_dof_states")
        if any(not isinstance(item, JointDofState) for item in joint_dof_states):
            raise ValueError("joint_dof_states は JointDofState の配列でなければなりません")
        if len({item.joint_id for item in joint_dof_states}) != len(joint_dof_states):
            raise ValueError("joint_dof_states の joint_id は一意でなければなりません")
        object.__setattr__(self, "history", history)
        object.__setattr__(
            self,
            "joint_dof_states",
            tuple(sorted(joint_dof_states, key=lambda item: item.joint_id)),
        )

    def validate_for(self, model: CanonicalBodyModel) -> None:
        if self.body_model_id != model.body_model_id:
            raise ValueError("BodyStateのbody_model_idがCanonicalBodyModelと一致しません")
        if (
            self.body_model_revision is not None
            and self.body_model_revision != model.body_model_revision
        ):
            raise ValueError("BodyStateのbody_model_revisionがCanonicalBodyModelと一致しません")
        if (
            self.body_model_fingerprint is not None
            and self.body_model_fingerprint != model.body_model_fingerprint
        ):
            raise ValueError("BodyStateのbody_model_fingerprintがCanonicalBodyModelと一致しません")
        self.pose.validate_for(model)
        self.velocity.validate_for(model)
        for _, pose in self.history:
            pose.validate_for(model)
        if self.joint_dof_states:
            by_joint = {item.joint_id: item for item in self.joint_dof_states}
            required = {item.joint_id for item in model.joints if item.limits}
            if set(by_joint) != required:
                raise ValueError(
                    "BodyStateのjoint_dof_states coverageがCanonicalBodyModelと一致しません"
                )
            joints = {item.joint_id: item for item in model.joints}
            for joint_id, state in by_joint.items():
                state.validate_for(joints[joint_id])

    def validate_physical_for(self, model: CanonicalBodyModel) -> None:
        self.validate_for(model)
        model.require_physical_control_contract()
        if self.body_model_revision is None or self.body_model_fingerprint is None:
            raise ValueError(
                "physical BodyStateはmodel revision/fingerprintを保持する必要があります"
            )
        if not self.joint_dof_states and any(item.limits for item in model.joints):
            raise ValueError("physical BodyStateはscalar joint_dof_statesを保持する必要があります")

    def to_dict(self) -> dict[str, object]:
        return {
            "body_model_id": self.body_model_id,
            "body_model_revision": self.body_model_revision,
            "body_model_fingerprint": self.body_model_fingerprint,
            "revision": self.revision,
            "observed_at": timestamp_to_json(self.observed_at),
            "joint_dof_states": [item.to_dict() for item in self.joint_dof_states],
            "pose": self.pose.to_dict(),
            "velocity": self.velocity.to_dict(),
            "history": [
                {"observed_at": timestamp_to_json(observed_at), "pose": pose.to_dict()}
                for observed_at, pose in self.history
            ],
        }
