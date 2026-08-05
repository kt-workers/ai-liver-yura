from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from app.domain.body_pose_frame import BodyPoseFrame


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class BodyKinematicPoint:
    """Bodyローカルの正規化座標。x=右、y=上、z=前。"""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    def translated(self, other: BodyKinematicPoint) -> BodyKinematicPoint:
        return BodyKinematicPoint(
            self.x + other.x,
            self.y + other.y,
            self.z + other.z,
        )

    def lerp(self, other: BodyKinematicPoint, amount: float) -> BodyKinematicPoint:
        alpha = max(0.0, min(1.0, _finite(amount, "amount")))
        return BodyKinematicPoint(
            self.x + (other.x - self.x) * alpha,
            self.y + (other.y - self.y) * alpha,
            self.z + (other.z - self.z) * alpha,
        )

    def distance_to(self, other: BodyKinematicPoint) -> float:
        return math.sqrt(
            (other.x - self.x) ** 2
            + (other.y - self.y) ** 2
            + (other.z - self.z) ** 2
        )

    def as_payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True, slots=True)
class BodyKinematicJoint:
    joint_id: str
    position: BodyKinematicPoint
    confidence: float = 1.0

    def __post_init__(self) -> None:
        joint_id = self.joint_id.strip().lower()
        if not joint_id or len(joint_id) > 80:
            raise ValueError("joint_id must contain 1 to 80 characters")
        confidence = _finite(self.confidence, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "joint_id", joint_id)
        object.__setattr__(self, "confidence", confidence)

    def as_payload(self) -> dict[str, object]:
        return {
            "joint_id": self.joint_id,
            "position": self.position.as_payload(),
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class BodyKinematicPose:
    """RendererやAvatar形式に依存しないCanonical関節位置。"""

    joints: tuple[BodyKinematicJoint, ...]
    root_position: BodyKinematicPoint = field(default_factory=BodyKinematicPoint)
    coordinate_space: str = "body_local_normalized"

    def __post_init__(self) -> None:
        joints = tuple(self.joints)
        joint_ids = [joint.joint_id for joint in joints]
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("kinematic joint ids must be unique")
        if not joints:
            raise ValueError("kinematic pose requires at least one joint")
        coordinate_space = self.coordinate_space.strip().lower()
        if not coordinate_space:
            raise ValueError("coordinate_space must not be empty")
        object.__setattr__(self, "joints", joints)
        object.__setattr__(self, "coordinate_space", coordinate_space)

    def positions(self) -> dict[str, BodyKinematicPoint]:
        return {joint.joint_id: joint.position for joint in self.joints}

    def joint(self, joint_id: str) -> BodyKinematicJoint | None:
        normalized = joint_id.strip().lower()
        return next(
            (joint for joint in self.joints if joint.joint_id == normalized),
            None,
        )

    def with_positions(
        self,
        positions: Mapping[str, BodyKinematicPoint],
        *,
        root_position: BodyKinematicPoint | None = None,
    ) -> BodyKinematicPose:
        current = self.positions()
        current.update({str(key).strip().lower(): value for key, value in positions.items()})
        ordered_ids = [joint.joint_id for joint in self.joints]
        extra_ids = [joint_id for joint_id in current if joint_id not in ordered_ids]
        return BodyKinematicPose(
            joints=tuple(
                BodyKinematicJoint(joint_id, current[joint_id])
                for joint_id in (*ordered_ids, *extra_ids)
            ),
            root_position=root_position or self.root_position,
            coordinate_space=self.coordinate_space,
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "coordinate_space": self.coordinate_space,
            "root_position": self.root_position.as_payload(),
            "joints": [joint.as_payload() for joint in self.joints],
        }


@dataclass(frozen=True, slots=True)
class GenerativeBodyPoseFrame:
    """既存BodyPoseFrameへ汎用関節姿勢と実行中Motion情報を付加する。

    BodyPoseFrameの3D投影フィールドを主契約として扱わず、kinematic_poseを
    棒人間、Live2D、3D Adapterが共通利用する。
    """

    base_frame: BodyPoseFrame
    kinematic_pose: BodyKinematicPose
    active_motion_ids: tuple[str, ...] = ()
    held_targets: tuple[str, ...] = ()
    motion_schema_version: int = 1

    @property
    def sequence(self) -> int:
        return self.base_frame.sequence

    @property
    def timestamp_ms(self) -> int:
        return self.base_frame.timestamp_ms

    @property
    def pose(self):  # type: ignore[no-untyped-def]
        return self.base_frame.pose

    @property
    def velocity(self):  # type: ignore[no-untyped-def]
        return self.base_frame.velocity

    @property
    def inner_state(self):  # type: ignore[no-untyped-def]
        return self.base_frame.inner_state

    @property
    def attention_target_id(self) -> str | None:
        return self.base_frame.attention_target_id

    @property
    def attention_dwell_ms(self) -> int:
        return self.base_frame.attention_dwell_ms

    def as_payload(self) -> dict[str, object]:
        payload = self.base_frame.as_payload()
        payload.update(
            {
                "motion_schema_version": self.motion_schema_version,
                "kinematic_pose": self.kinematic_pose.as_payload(),
                "active_motion_ids": list(self.active_motion_ids),
                "held_targets": list(self.held_targets),
            }
        )
        return payload
