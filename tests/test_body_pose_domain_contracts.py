from __future__ import annotations

import math

import pytest

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
from app.domain.body_pose_frame import (
    BODY_POSE_FRAME_SCHEMA_VERSION,
    BodyPoseFrame,
)
from app.domain.body_skeleton import (
    CANONICAL_BODY_JOINT_IDS,
    BodyJointPose,
    CanonicalBodyJoint,
)

pytestmark = pytest.mark.unit


def _frame(
    *,
    joints: tuple[BodyJointPose, ...] = (),
    blend_shapes: tuple[BodyBlendShape, ...] = (),
) -> BodyPoseFrame:
    return BodyPoseFrame(
        sequence=3,
        timestamp_ms=1200,
        pose=BodyTrackingPose(head_yaw=0.2, mouth_open=0.4),
        velocity=BodyTrackingVelocity(head_yaw=0.5),
        inner_state=BodyInnerMotionState(engagement=0.8),
        joints=joints,
        blend_shapes=blend_shapes,
        attention_target_id="conversation_partner",
        attention_dwell_ms=420,
    )


def test_body_quaternion_normalizes_and_serializes() -> None:
    quaternion = BodyQuaternion.from_euler_radians(x=0.4, y=-0.7, z=0.2)
    length = math.sqrt(
        quaternion.x**2
        + quaternion.y**2
        + quaternion.z**2
        + quaternion.w**2
    )

    assert length == pytest.approx(1.0)
    assert set(quaternion.as_payload()) == {"x", "y", "z", "w"}


def test_body_geometry_rejects_non_finite_and_invalid_scale() -> None:
    with pytest.raises(ValueError, match="x must be finite"):
        BodyVector3(float("nan"), 0.0, 0.0)
    with pytest.raises(ValueError, match="quaternion must not be zero"):
        BodyQuaternion(0.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="transform scale must be positive"):
        BodyTransform3D(scale=BodyVector3(1.0, 0.0, 1.0))


def test_body_gaze_direction_is_normalized() -> None:
    gaze = BodyGazeVector(direction=BodyVector3(2.0, 0.0, 0.0))

    assert gaze.direction == BodyVector3(1.0, 0.0, 0.0)


def test_attention_candidate_only_validates_perception_contract() -> None:
    candidate = BodyAttentionCandidate(
        " left_light ",
        -0.8,
        0.25,
        salience=0.9,
        novelty=0.7,
        threat=0.1,
        relevance=0.6,
        stability=0.8,
    )

    assert candidate.candidate_id == "left_light"
    assert candidate.as_payload()["novelty"] == 0.7
    with pytest.raises(ValueError, match="x must be between -1.0 and 1.0"):
        BodyAttentionCandidate("outside", 1.1, 0.0)


def test_inner_motion_state_is_a_bounded_snapshot() -> None:
    state = BodyInnerMotionState(
        arousal=0.8,
        tension=0.2,
        curiosity=0.6,
        confidence=0.7,
        engagement=0.9,
        avoidance=0.1,
        movement_energy=0.75,
    )

    assert state.as_payload()["movement_energy"] == 0.75
    with pytest.raises(ValueError, match="engagement must be between 0.0 and 1.0"):
        BodyInnerMotionState(engagement=1.01)


def test_canonical_joint_and_blend_shape_names_are_model_independent() -> None:
    assert CanonicalBodyJoint.HEAD.value == "head"
    assert CanonicalBodyBlendShape.JAW_OPEN.value == "jaw_open"
    assert "head" in CANONICAL_BODY_JOINT_IDS
    assert "jaw_open" in CANONICAL_BODY_BLEND_SHAPE_NAMES
    assert not any("param" in name.lower() for name in CANONICAL_BODY_JOINT_IDS)
    assert not any("param" in name.lower() for name in CANONICAL_BODY_BLEND_SHAPE_NAMES)


def test_skeleton_and_blend_shape_allow_contract_extensions() -> None:
    custom_joint = BodyJointPose("left_wrist")
    custom_shape = BodyBlendShape("brow_inner_up", 0.4)

    assert custom_joint.is_canonical is False
    assert custom_shape.is_canonical is False
    assert BodyJointPose(" HEAD ").is_canonical is True
    assert BodyBlendShape(" JAW_OPEN ", 0.2).is_canonical is True


def test_auxiliary_projection_validates_pose_and_velocity_separately() -> None:
    pose = BodyTrackingPose(
        head_yaw=-0.8,
        eye_left_open=0.5,
        left_arm_raise=1.0,
    )
    velocity = BodyTrackingVelocity(head_yaw=7.5, mouth_open=-2.0)

    assert pose.as_payload()["left_arm_raise"] == 1.0
    assert velocity.as_payload()["head_yaw"] == 7.5
    with pytest.raises(ValueError, match="eye_left_open must be between 0.0 and 1.0"):
        BodyTrackingPose(eye_left_open=-0.1)
    with pytest.raises(ValueError, match="head_yaw must be between -8.0 and 8.0"):
        BodyTrackingVelocity(head_yaw=8.1)


def test_body_pose_frame_preserves_schema_v2_payload() -> None:
    frame = _frame(
        joints=(
            BodyJointPose(CanonicalBodyJoint.HIPS.value),
            BodyJointPose(CanonicalBodyJoint.HEAD.value),
            BodyJointPose("left_wrist"),
        ),
        blend_shapes=(
            BodyBlendShape(CanonicalBodyBlendShape.JAW_OPEN.value, 0.4),
            BodyBlendShape("brow_inner_up", 0.2),
        ),
    )

    payload = frame.as_payload()

    assert frame.schema_version == BODY_POSE_FRAME_SCHEMA_VERSION == 2
    assert frame.coordinate_space is BodyCoordinateSpace.RIGHT_HANDED_Y_UP
    assert frame.canonical_joint_ids == {"hips", "head"}
    assert frame.canonical_blend_shape_names == {"jaw_open"}
    assert payload["coordinate_space"] == "right_handed_y_up"
    assert payload["joints"][0]["joint_id"] == "hips"  # type: ignore[index]
    assert payload["attention_target_id"] == "conversation_partner"
    assert frame.to_dict() == payload


def test_body_pose_frame_accepts_coordinate_space_compatibility_string() -> None:
    frame = BodyPoseFrame(
        sequence=0,
        timestamp_ms=0,
        pose=BodyTrackingPose(),
        velocity=BodyTrackingVelocity(),
        inner_state=BodyInnerMotionState(),
        coordinate_space="right_handed_y_up",  # type: ignore[arg-type]
    )

    assert frame.coordinate_space is BodyCoordinateSpace.RIGHT_HANDED_Y_UP


def test_body_pose_frame_rejects_duplicate_joint_and_shape_names() -> None:
    head = BodyJointPose("head")
    blink = BodyBlendShape("eye_blink_left", 0.3)

    with pytest.raises(ValueError, match="joint ids must be unique"):
        _frame(joints=(head, head))
    with pytest.raises(ValueError, match="blend shape names must be unique"):
        _frame(blend_shapes=(blink, blink))


def test_body_pose_frame_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version must be 2"):
        BodyPoseFrame(
            sequence=0,
            timestamp_ms=0,
            pose=BodyTrackingPose(),
            velocity=BodyTrackingVelocity(),
            inner_state=BodyInnerMotionState(),
            schema_version=1,
        )


def test_legacy_body_pose_frame_module_reexports_split_contracts() -> None:
    from app.domain.body_pose_frame import (  # noqa: PLC0415
        BodyAttentionCandidate as ExportedAttentionCandidate,
        BodyBlendShape as ExportedBlendShape,
        BodyJointPose as ExportedJointPose,
        BodyQuaternion as ExportedQuaternion,
    )

    assert ExportedAttentionCandidate is BodyAttentionCandidate
    assert ExportedBlendShape is BodyBlendShape
    assert ExportedJointPose is BodyJointPose
    assert ExportedQuaternion is BodyQuaternion
