from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_auxiliary_projection import (
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.domain.body_blend_shape import (
    CANONICAL_BODY_BLEND_SHAPE_NAMES,
    BodyBlendShape,
    CanonicalBodyBlendShape,
)
from app.domain.body_geometry import (
    BodyCoordinateSpace,
    BodyGazeVector,
    BodyQuaternion,
    BodyTransform3D,
    BodyVector3,
)
from app.domain.body_motion_state import BodyInnerMotionState
from app.domain.body_skeleton import (
    CANONICAL_BODY_JOINT_IDS,
    BodyJointPose,
    CanonicalBodyJoint,
)
from app.domain.body_value_validation import (
    non_negative_integer,
    normalized_identifier,
)

BODY_POSE_FRAME_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class BodyPoseFrame:
    """一定周期で出力するモデル非依存Body Pose集約。

    root_transform・joints・blend_shapes・gaze_vectorが3D向けの主契約で、
    pose・velocityは棒人形／Live2D Adapter向けの補助投影である。
    """

    sequence: int
    timestamp_ms: int
    pose: BodyTrackingPose
    velocity: BodyTrackingVelocity
    inner_state: BodyInnerMotionState
    root_transform: BodyTransform3D = field(default_factory=BodyTransform3D)
    joints: tuple[BodyJointPose, ...] = ()
    blend_shapes: tuple[BodyBlendShape, ...] = ()
    gaze_vector: BodyGazeVector = field(default_factory=BodyGazeVector)
    coordinate_space: BodyCoordinateSpace = BodyCoordinateSpace.RIGHT_HANDED_Y_UP
    attention_target_id: str | None = None
    attention_dwell_ms: int = 0
    schema_version: int = BODY_POSE_FRAME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sequence",
            non_negative_integer(self.sequence, "sequence"),
        )
        object.__setattr__(
            self,
            "timestamp_ms",
            non_negative_integer(self.timestamp_ms, "timestamp_ms"),
        )
        object.__setattr__(
            self,
            "attention_dwell_ms",
            non_negative_integer(self.attention_dwell_ms, "attention_dwell_ms"),
        )
        if self.schema_version != BODY_POSE_FRAME_SCHEMA_VERSION:
            raise ValueError(
                "schema_version must be "
                f"{BODY_POSE_FRAME_SCHEMA_VERSION}"
            )

        coordinate_space = self.coordinate_space
        if isinstance(coordinate_space, str):
            coordinate_space = BodyCoordinateSpace(coordinate_space)
        if not isinstance(coordinate_space, BodyCoordinateSpace):
            raise TypeError("coordinate_space must be BodyCoordinateSpace")
        object.__setattr__(self, "coordinate_space", coordinate_space)

        if self.attention_target_id is not None:
            object.__setattr__(
                self,
                "attention_target_id",
                normalized_identifier(
                    self.attention_target_id,
                    "attention_target_id",
                ),
            )

        joints = tuple(self.joints)
        if not all(isinstance(joint, BodyJointPose) for joint in joints):
            raise TypeError("joints must contain BodyJointPose values")
        joint_ids = [joint.joint_id for joint in joints]
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("joint ids must be unique")
        object.__setattr__(self, "joints", joints)

        blend_shapes = tuple(self.blend_shapes)
        if not all(isinstance(shape, BodyBlendShape) for shape in blend_shapes):
            raise TypeError("blend_shapes must contain BodyBlendShape values")
        shape_names = [shape.name for shape in blend_shapes]
        if len(shape_names) != len(set(shape_names)):
            raise ValueError("blend shape names must be unique")
        object.__setattr__(self, "blend_shapes", blend_shapes)

    @property
    def canonical_joint_ids(self) -> frozenset[str]:
        return frozenset(
            joint.joint_id for joint in self.joints if joint.is_canonical
        )

    @property
    def canonical_blend_shape_names(self) -> frozenset[str]:
        return frozenset(
            shape.name for shape in self.blend_shapes if shape.is_canonical
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "timestamp_ms": self.timestamp_ms,
            "coordinate_space": self.coordinate_space.value,
            "root_transform": self.root_transform.as_payload(),
            "joints": [joint.as_payload() for joint in self.joints],
            "blend_shapes": [shape.as_payload() for shape in self.blend_shapes],
            "gaze_vector": self.gaze_vector.as_payload(),
            "pose": self.pose.as_payload(),
            "velocity": self.velocity.as_payload(),
            "inner_state": self.inner_state.as_payload(),
            "attention_target_id": self.attention_target_id,
            "attention_dwell_ms": self.attention_dwell_ms,
        }

    def to_dict(self) -> dict[str, object]:
        """Connector／Adapter向けの互換別名。"""

        return self.as_payload()


__all__ = [
    "BODY_POSE_FRAME_SCHEMA_VERSION",
    "CANONICAL_BODY_BLEND_SHAPE_NAMES",
    "CANONICAL_BODY_JOINT_IDS",
    "BodyAttentionCandidate",
    "BodyBlendShape",
    "BodyCoordinateSpace",
    "BodyGazeVector",
    "BodyInnerMotionState",
    "BodyJointPose",
    "BodyPoseFrame",
    "BodyQuaternion",
    "BodyTrackingPose",
    "BodyTrackingVelocity",
    "BodyTransform3D",
    "BodyVector3",
    "CanonicalBodyBlendShape",
    "CanonicalBodyJoint",
]
