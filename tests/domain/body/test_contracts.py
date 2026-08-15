import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.body import (
    AnatomicalRegion,
    AnatomicalSide,
    Axis,
    BodyPose,
    BodyState,
    BodyVelocity,
    CanonicalBodyModel,
    CenterOfMassReference,
    JointDefinition,
    JointLimit,
    JointTransform,
    JointVelocity,
    KinematicChain,
    Quaternion,
    SegmentDefinition,
    Vector3,
)


def transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def velocity() -> JointVelocity:
    return JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))


def joint(joint_id: str, parent_joint_id: str | None, side: AnatomicalSide) -> JointDefinition:
    return JointDefinition(
        joint_id,
        parent_joint_id,
        AnatomicalRegion.ROOT if parent_joint_id is None else AnatomicalRegion.ARM,
        side,
        transform(),
        (JointLimit(Axis.Z, -1, 1, -0.5, 0.5, 0),),
    )


def model() -> CanonicalBodyModel:
    return CanonicalBodyModel(
        "yura.canonical.v1",
        (
            joint("root", None, AnatomicalSide.CENTER),
            joint("right_hand", "root", AnatomicalSide.RIGHT),
        ),
        (SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1),),
        ("right_hand",),
        (KinematicChain("right_arm", ("root", "right_hand"), "right_hand"),),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
    )


def pose() -> BodyPose:
    return BodyPose(transform(), (("right_hand", transform()),))


def body_velocity() -> BodyVelocity:
    return BodyVelocity(velocity(), (("right_hand", velocity()),))


def test_canonical_model_keeps_anatomical_sides_and_renderer_independent_coordinates() -> None:
    value = model().to_dict()
    assert value["coordinate_system"] == {
        "handedness": "right",
        "x": "anatomical_right",
        "y": "up",
        "z": "forward",
    }
    assert value["joints"][1]["side"] == "right"  # type: ignore[index]


def test_model_and_state_are_immutable_and_json_serializable() -> None:
    current = datetime(2026, 8, 15, tzinfo=timezone.utc)
    state = BodyState(model().body_model_id, 2, current, pose(), body_velocity())
    state.validate_for(model())
    assert state.to_dict()["revision"] == 2
    assert json.loads(json.dumps(state.to_dict()))["body_model_id"] == "yura.canonical.v1"
    with pytest.raises(FrozenInstanceError):
        state.revision = 3  # type: ignore[misc]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_finite_number_contract_rejects_non_finite_position_and_rotation(value: float) -> None:
    with pytest.raises(ValueError, match="有限"):
        Vector3(value, 0, 0)
    with pytest.raises(ValueError, match="有限"):
        Quaternion(0, 0, 0, value)


def test_quaternion_must_be_normalized() -> None:
    with pytest.raises(ValueError, match="単位長"):
        Quaternion(0, 0, 0, 2)


def test_joint_limit_enforces_dof_hard_and_comfortable_ranges() -> None:
    with pytest.raises(ValueError, match="hard range"):
        JointLimit(Axis.X, 1, -1, 0, 0, 0)
    with pytest.raises(ValueError, match="comfortable range"):
        JointLimit(Axis.X, -1, 1, -2, 0, 0)
    with pytest.raises(ValueError, match="relaxed"):
        JointLimit(Axis.X, -1, 1, -0.5, 0.5, 0.8)


def test_joint_rejects_duplicate_dof_and_self_parent() -> None:
    with pytest.raises(ValueError, match="重複"):
        JointDefinition(
            "root",
            None,
            AnatomicalRegion.ROOT,
            AnatomicalSide.CENTER,
            transform(),
            (JointLimit(Axis.X, -1, 1, -1, 1, 0), JointLimit(Axis.X, -1, 1, -1, 1, 0)),
        )
    with pytest.raises(ValueError, match="自分自身"):
        joint("root", "root", AnatomicalSide.CENTER)


def test_model_rejects_unknown_parent_and_multiple_roots() -> None:
    with pytest.raises(ValueError, match="既知joint"):
        CanonicalBodyModel(
            "model",
            (joint("hand", "missing", AnatomicalSide.RIGHT),),
            (),
            (),
            (),
            CenterOfMassReference("hand", Vector3(0, 0, 0)),
        )
    with pytest.raises(ValueError, match="root joint"):
        CanonicalBodyModel(
            "model",
            (
                joint("root_a", None, AnatomicalSide.CENTER),
                joint("root_b", None, AnatomicalSide.CENTER),
            ),
            (),
            (),
            (),
            CenterOfMassReference("root_a", Vector3(0, 0, 0)),
        )


def test_model_rejects_cycle_segment_and_chain_that_are_not_continuous() -> None:
    first = joint("first", "second", AnatomicalSide.CENTER)
    second = joint("second", "first", AnatomicalSide.CENTER)
    with pytest.raises(ValueError, match="cycle"):
        CanonicalBodyModel(
            "model", (first, second), (), (), (), CenterOfMassReference("first", Vector3(0, 0, 0))
        )
    with pytest.raises(ValueError, match="直接の親子"):
        CanonicalBodyModel(
            "model",
            (
                joint("root", None, AnatomicalSide.CENTER),
                joint("hand", "root", AnatomicalSide.RIGHT),
            ),
            (SegmentDefinition("bad", "hand", "root", 0.1, 1),),
            (),
            (),
            CenterOfMassReference("root", Vector3(0, 0, 0)),
        )


def test_model_rejects_unknown_or_duplicate_end_effector_and_bad_chain_end() -> None:
    base_joints = (
        joint("root", None, AnatomicalSide.CENTER),
        joint("hand", "root", AnatomicalSide.RIGHT),
    )
    with pytest.raises(ValueError, match="end effector"):
        CanonicalBodyModel(
            "model",
            base_joints,
            (),
            ("missing",),
            (),
            CenterOfMassReference("root", Vector3(0, 0, 0)),
        )
    with pytest.raises(ValueError, match="末端"):
        KinematicChain("arm", ("root", "hand"), "root")


def test_pose_and_velocity_must_cover_exactly_the_model_skeleton() -> None:
    canonical = model()
    invalid_pose = BodyPose(transform(), (("root", transform()), ("right_hand", transform())))
    with pytest.raises(ValueError, match="root以外"):
        invalid_pose.validate_for(canonical)
    invalid_velocity = BodyVelocity(velocity(), (("root", velocity()), ("right_hand", velocity())))
    with pytest.raises(ValueError, match="root以外"):
        invalid_velocity.validate_for(canonical)


def test_body_state_requires_matching_model_and_non_future_immutable_history() -> None:
    current = datetime(2026, 8, 15, tzinfo=timezone.utc)
    previous = pose()
    state = BodyState(
        "other", 0, current, pose(), body_velocity(), ((current - timedelta(seconds=1), previous),)
    )
    with pytest.raises(ValueError, match="一致"):
        state.validate_for(model())
    with pytest.raises(ValueError, match="新しく"):
        BodyState(
            model().body_model_id,
            0,
            current,
            pose(),
            body_velocity(),
            ((current + timedelta(seconds=1), previous),),
        )


def test_segment_rejects_non_positive_or_non_finite_normalized_values() -> None:
    with pytest.raises(ValueError, match="正"):
        SegmentDefinition("segment", "a", "b", 0, 1)
    with pytest.raises(ValueError, match="有限"):
        SegmentDefinition("segment", "a", "b", float("nan"), 1)
