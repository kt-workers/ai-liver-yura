from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from app.domain.body_geometry import BodyVector3
from app.domain.body_skeleton import CanonicalBodyJoint
from app.domain.body_value_validation import (
    bounded_number,
    finite_number,
    normalized_identifier,
)


class BodyJointAxis(str, Enum):
    """Canonical jointのモデル非依存回転自由度。"""

    PITCH = "pitch"
    YAW = "yaw"
    ROLL = "roll"


@dataclass(frozen=True, slots=True)
class BodyJointDof:
    axis: BodyJointAxis
    minimum_radians: float
    maximum_radians: float
    preferred_radians: float = 0.0
    comfort_weight: float = 1.0

    def __post_init__(self) -> None:
        axis = self.axis
        if isinstance(axis, str):
            axis = BodyJointAxis(axis)
        if not isinstance(axis, BodyJointAxis):
            raise TypeError("axis must be BodyJointAxis")
        minimum = finite_number(self.minimum_radians, "minimum_radians")
        maximum = finite_number(self.maximum_radians, "maximum_radians")
        preferred = finite_number(self.preferred_radians, "preferred_radians")
        if minimum >= maximum:
            raise ValueError("minimum_radians must be smaller than maximum_radians")
        if not minimum <= preferred <= maximum:
            raise ValueError("preferred_radians must be within the joint limit")
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "minimum_radians", minimum)
        object.__setattr__(self, "maximum_radians", maximum)
        object.__setattr__(self, "preferred_radians", preferred)
        object.__setattr__(
            self,
            "comfort_weight",
            bounded_number(self.comfort_weight, "comfort_weight", 0.0, 1.0),
        )

    def clamp(self, value: float) -> float:
        normalized = finite_number(value, "joint_angle")
        return max(self.minimum_radians, min(self.maximum_radians, normalized))


@dataclass(frozen=True, slots=True)
class BodyJointDefinition:
    joint_id: str
    parent_id: str | None
    local_offset: BodyVector3
    dofs: tuple[BodyJointDof, ...] = ()

    def __post_init__(self) -> None:
        joint_id = normalized_identifier(
            self.joint_id,
            "joint_id",
            lowercase=True,
            maximum_length=80,
        )
        parent_id = self.parent_id
        if parent_id is not None:
            parent_id = normalized_identifier(
                parent_id,
                "parent_id",
                lowercase=True,
                maximum_length=80,
            )
            if parent_id == joint_id:
                raise ValueError("joint cannot be its own parent")
        if not isinstance(self.local_offset, BodyVector3):
            raise TypeError("local_offset must be BodyVector3")
        dofs = tuple(self.dofs)
        if not all(isinstance(value, BodyJointDof) for value in dofs):
            raise TypeError("dofs must contain BodyJointDof values")
        axes = [value.axis for value in dofs]
        if len(axes) != len(set(axes)):
            raise ValueError("joint DOF axes must be unique")
        object.__setattr__(self, "joint_id", joint_id)
        object.__setattr__(self, "parent_id", parent_id)
        object.__setattr__(self, "dofs", dofs)

    def dof(self, axis: BodyJointAxis) -> BodyJointDof | None:
        for value in self.dofs:
            if value.axis is axis:
                return value
        return None

    def clamp_euler(self, value: BodyVector3) -> BodyVector3:
        if not isinstance(value, BodyVector3):
            raise TypeError("value must be BodyVector3")
        axis_values = {
            BodyJointAxis.PITCH: value.x,
            BodyJointAxis.YAW: value.y,
            BodyJointAxis.ROLL: value.z,
        }
        clamped: dict[BodyJointAxis, float] = {}
        for axis, angle in axis_values.items():
            dof = self.dof(axis)
            clamped[axis] = 0.0 if dof is None else dof.clamp(angle)
        return BodyVector3(
            clamped[BodyJointAxis.PITCH],
            clamped[BodyJointAxis.YAW],
            clamped[BodyJointAxis.ROLL],
        )


@dataclass(frozen=True, slots=True)
class BodyKinematicChain:
    chain_id: str
    joint_ids: tuple[str, ...]
    end_effector_id: str

    def __post_init__(self) -> None:
        chain_id = normalized_identifier(
            self.chain_id,
            "chain_id",
            lowercase=True,
            maximum_length=80,
        )
        joint_ids = tuple(
            normalized_identifier(
                value,
                "joint_id",
                lowercase=True,
                maximum_length=80,
            )
            for value in self.joint_ids
        )
        if len(joint_ids) < 2:
            raise ValueError("kinematic chain must contain at least two joints")
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("kinematic chain joints must be unique")
        end_effector_id = normalized_identifier(
            self.end_effector_id,
            "end_effector_id",
            lowercase=True,
            maximum_length=80,
        )
        if end_effector_id != joint_ids[-1]:
            raise ValueError("end_effector_id must be the last joint in the chain")
        object.__setattr__(self, "chain_id", chain_id)
        object.__setattr__(self, "joint_ids", joint_ids)
        object.__setattr__(self, "end_effector_id", end_effector_id)


@dataclass(frozen=True, slots=True)
class BodySkeletonProfile:
    """Bodyが所有するモデル非依存Skeleton/DOF/chain定義。"""

    joints: tuple[BodyJointDefinition, ...]
    chains: tuple[BodyKinematicChain, ...]
    center_of_mass_joint_id: str = CanonicalBodyJoint.HIPS.value

    def __post_init__(self) -> None:
        joints = tuple(self.joints)
        chains = tuple(self.chains)
        if not joints:
            raise ValueError("joints must not be empty")
        if not all(isinstance(value, BodyJointDefinition) for value in joints):
            raise TypeError("joints must contain BodyJointDefinition values")
        if not all(isinstance(value, BodyKinematicChain) for value in chains):
            raise TypeError("chains must contain BodyKinematicChain values")
        joint_ids = [value.joint_id for value in joints]
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("joint ids must be unique")
        known = set(joint_ids)
        roots = [value for value in joints if value.parent_id is None]
        if len(roots) != 1:
            raise ValueError("skeleton must contain exactly one root joint")
        for joint in joints:
            if joint.parent_id is not None and joint.parent_id not in known:
                raise ValueError(f"unknown parent joint: {joint.parent_id}")
        chain_ids = [value.chain_id for value in chains]
        if len(chain_ids) != len(set(chain_ids)):
            raise ValueError("chain ids must be unique")
        for chain in chains:
            if any(value not in known for value in chain.joint_ids):
                raise ValueError(f"chain {chain.chain_id} contains an unknown joint")
        center = normalized_identifier(
            self.center_of_mass_joint_id,
            "center_of_mass_joint_id",
            lowercase=True,
            maximum_length=80,
        )
        if center not in known:
            raise ValueError("center_of_mass_joint_id must reference a known joint")
        object.__setattr__(self, "joints", joints)
        object.__setattr__(self, "chains", chains)
        object.__setattr__(self, "center_of_mass_joint_id", center)

    @property
    def root_joint_id(self) -> str:
        return next(value.joint_id for value in self.joints if value.parent_id is None)

    def joint(self, joint_id: str) -> BodyJointDefinition:
        normalized = normalized_identifier(
            joint_id,
            "joint_id",
            lowercase=True,
            maximum_length=80,
        )
        for value in self.joints:
            if value.joint_id == normalized:
                return value
        raise KeyError(normalized)

    def chain(self, chain_id: str) -> BodyKinematicChain:
        normalized = normalized_identifier(
            chain_id,
            "chain_id",
            lowercase=True,
            maximum_length=80,
        )
        for value in self.chains:
            if value.chain_id == normalized:
                return value
        raise KeyError(normalized)

    def chain_for_end_effector(self, end_effector_id: str) -> BodyKinematicChain:
        normalized = normalized_identifier(
            end_effector_id,
            "end_effector_id",
            lowercase=True,
            maximum_length=80,
        )
        for value in self.chains:
            if value.end_effector_id == normalized:
                return value
        raise KeyError(normalized)

    @classmethod
    def canonical_humanoid(cls) -> BodySkeletonProfile:
        def dof(
            axis: BodyJointAxis,
            minimum_deg: float,
            maximum_deg: float,
            preferred_deg: float = 0.0,
            comfort_weight: float = 1.0,
        ) -> BodyJointDof:
            return BodyJointDof(
                axis=axis,
                minimum_radians=math.radians(minimum_deg),
                maximum_radians=math.radians(maximum_deg),
                preferred_radians=math.radians(preferred_deg),
                comfort_weight=comfort_weight,
            )

        pitch = BodyJointAxis.PITCH
        yaw = BodyJointAxis.YAW
        roll = BodyJointAxis.ROLL
        j = CanonicalBodyJoint

        joints = (
            BodyJointDefinition(
                j.HIPS.value,
                None,
                BodyVector3(0.0, 0.92, 0.0),
                (dof(pitch, -45, 45), dof(yaw, -50, 50), dof(roll, -35, 35)),
            ),
            BodyJointDefinition(
                j.SPINE.value,
                j.HIPS.value,
                BodyVector3(0.0, 0.18, 0.0),
                (dof(pitch, -30, 35), dof(yaw, -30, 30), dof(roll, -25, 25)),
            ),
            BodyJointDefinition(
                j.CHEST.value,
                j.SPINE.value,
                BodyVector3(0.0, 0.22, 0.0),
                (dof(pitch, -30, 35), dof(yaw, -40, 40), dof(roll, -30, 30)),
            ),
            BodyJointDefinition(
                j.NECK.value,
                j.CHEST.value,
                BodyVector3(0.0, 0.18, 0.0),
                (dof(pitch, -45, 45), dof(yaw, -60, 60), dof(roll, -40, 40)),
            ),
            BodyJointDefinition(
                j.HEAD.value,
                j.NECK.value,
                BodyVector3(0.0, 0.13, 0.0),
                (dof(pitch, -35, 35), dof(yaw, -50, 50), dof(roll, -30, 30)),
            ),
            BodyJointDefinition(
                j.LEFT_CLAVICLE.value,
                j.CHEST.value,
                BodyVector3(-0.13, 0.10, 0.0),
                (dof(pitch, -20, 25), dof(yaw, -20, 20), dof(roll, -25, 25)),
            ),
            BodyJointDefinition(
                j.RIGHT_CLAVICLE.value,
                j.CHEST.value,
                BodyVector3(0.13, 0.10, 0.0),
                (dof(pitch, -20, 25), dof(yaw, -20, 20), dof(roll, -25, 25)),
            ),
            BodyJointDefinition(
                j.LEFT_UPPER_ARM.value,
                j.LEFT_CLAVICLE.value,
                BodyVector3(-0.19, 0.0, 0.0),
                (dof(pitch, -150, 150), dof(yaw, -110, 110), dof(roll, -130, 130)),
            ),
            BodyJointDefinition(
                j.RIGHT_UPPER_ARM.value,
                j.RIGHT_CLAVICLE.value,
                BodyVector3(0.19, 0.0, 0.0),
                (dof(pitch, -150, 150), dof(yaw, -110, 110), dof(roll, -130, 130)),
            ),
            BodyJointDefinition(
                j.LEFT_LOWER_ARM.value,
                j.LEFT_UPPER_ARM.value,
                BodyVector3(-0.27, 0.0, 0.0),
                (dof(pitch, 0, 155, 12), dof(yaw, -25, 25), dof(roll, -95, 95)),
            ),
            BodyJointDefinition(
                j.RIGHT_LOWER_ARM.value,
                j.RIGHT_UPPER_ARM.value,
                BodyVector3(0.27, 0.0, 0.0),
                (dof(pitch, 0, 155, 12), dof(yaw, -25, 25), dof(roll, -95, 95)),
            ),
            BodyJointDefinition(
                j.LEFT_HAND.value,
                j.LEFT_LOWER_ARM.value,
                BodyVector3(-0.23, 0.0, 0.0),
                (dof(pitch, -75, 75), dof(yaw, -35, 35), dof(roll, -50, 50)),
            ),
            BodyJointDefinition(
                j.RIGHT_HAND.value,
                j.RIGHT_LOWER_ARM.value,
                BodyVector3(0.23, 0.0, 0.0),
                (dof(pitch, -75, 75), dof(yaw, -35, 35), dof(roll, -50, 50)),
            ),
            BodyJointDefinition(
                j.LEFT_UPPER_LEG.value,
                j.HIPS.value,
                BodyVector3(-0.09, -0.10, 0.0),
                (dof(pitch, -120, 55), dof(yaw, -45, 45), dof(roll, -35, 35)),
            ),
            BodyJointDefinition(
                j.RIGHT_UPPER_LEG.value,
                j.HIPS.value,
                BodyVector3(0.09, -0.10, 0.0),
                (dof(pitch, -120, 55), dof(yaw, -45, 45), dof(roll, -35, 35)),
            ),
            BodyJointDefinition(
                j.LEFT_LOWER_LEG.value,
                j.LEFT_UPPER_LEG.value,
                BodyVector3(0.0, -0.42, 0.0),
                (dof(pitch, 0, 155, 5),),
            ),
            BodyJointDefinition(
                j.RIGHT_LOWER_LEG.value,
                j.RIGHT_UPPER_LEG.value,
                BodyVector3(0.0, -0.42, 0.0),
                (dof(pitch, 0, 155, 5),),
            ),
            BodyJointDefinition(
                j.LEFT_FOOT.value,
                j.LEFT_LOWER_LEG.value,
                BodyVector3(0.0, -0.40, 0.05),
                (dof(pitch, -50, 65), dof(roll, -30, 30)),
            ),
            BodyJointDefinition(
                j.RIGHT_FOOT.value,
                j.RIGHT_LOWER_LEG.value,
                BodyVector3(0.0, -0.40, 0.05),
                (dof(pitch, -50, 65), dof(roll, -30, 30)),
            ),
        )
        chains = (
            BodyKinematicChain(
                "left_arm",
                (
                    j.LEFT_CLAVICLE.value,
                    j.LEFT_UPPER_ARM.value,
                    j.LEFT_LOWER_ARM.value,
                    j.LEFT_HAND.value,
                ),
                j.LEFT_HAND.value,
            ),
            BodyKinematicChain(
                "right_arm",
                (
                    j.RIGHT_CLAVICLE.value,
                    j.RIGHT_UPPER_ARM.value,
                    j.RIGHT_LOWER_ARM.value,
                    j.RIGHT_HAND.value,
                ),
                j.RIGHT_HAND.value,
            ),
            BodyKinematicChain(
                "left_leg",
                (
                    j.HIPS.value,
                    j.LEFT_UPPER_LEG.value,
                    j.LEFT_LOWER_LEG.value,
                    j.LEFT_FOOT.value,
                ),
                j.LEFT_FOOT.value,
            ),
            BodyKinematicChain(
                "right_leg",
                (
                    j.HIPS.value,
                    j.RIGHT_UPPER_LEG.value,
                    j.RIGHT_LOWER_LEG.value,
                    j.RIGHT_FOOT.value,
                ),
                j.RIGHT_FOOT.value,
            ),
            BodyKinematicChain(
                "head",
                (j.SPINE.value, j.CHEST.value, j.NECK.value, j.HEAD.value),
                j.HEAD.value,
            ),
        )
        return cls(joints=joints, chains=chains)


__all__ = [
    "BodyJointAxis",
    "BodyJointDefinition",
    "BodyJointDof",
    "BodyKinematicChain",
    "BodySkeletonProfile",
]
