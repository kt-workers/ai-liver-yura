from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.domain.body_geometry import BodyQuaternion, BodyVector3
from app.domain.body_value_validation import bounded_number, normalized_identifier


class CanonicalBodyJoint(str, Enum):
    """初期BodyPoseFrame契約が定義するモデル非依存Joint。"""

    HIPS = "hips"
    SPINE = "spine"
    CHEST = "chest"
    NECK = "neck"
    HEAD = "head"
    LEFT_UPPER_ARM = "left_upper_arm"
    RIGHT_UPPER_ARM = "right_upper_arm"
    LEFT_LOWER_ARM = "left_lower_arm"
    RIGHT_LOWER_ARM = "right_lower_arm"


CANONICAL_BODY_JOINT_IDS: frozenset[str] = frozenset(
    joint.value for joint in CanonicalBodyJoint
)


@dataclass(frozen=True, slots=True)
class BodyJointPose:
    """Canonicalまたは拡張Jointのローカル姿勢。

    モデル固有Bone名への変換はAvatar Adapterが担当する。
    """

    joint_id: str
    rotation: BodyQuaternion = field(default_factory=BodyQuaternion)
    position: BodyVector3 | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "joint_id",
            normalized_identifier(
                self.joint_id,
                "joint_id",
                lowercase=True,
            ),
        )
        object.__setattr__(
            self,
            "confidence",
            bounded_number(self.confidence, "confidence", 0.0, 1.0),
        )

    @property
    def is_canonical(self) -> bool:
        return self.joint_id in CANONICAL_BODY_JOINT_IDS

    def as_payload(self) -> dict[str, object]:
        return {
            "joint_id": self.joint_id,
            "rotation": self.rotation.as_payload(),
            "position": self.position.as_payload() if self.position is not None else None,
            "confidence": self.confidence,
        }
