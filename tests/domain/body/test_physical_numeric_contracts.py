from datetime import datetime, timezone
from math import pi

import pytest

from app.domain.body import (
    AnatomicalRegion,
    AnatomicalSide,
    Axis,
    BodyState,
    BodyVelocity,
    CanonicalBodyModel,
    CenterOfMassReference,
    ContactPointDefinition,
    EndEffectorDefinition,
    JointDefinition,
    JointDofCoordinate,
    JointDofState,
    JointDynamicLimit,
    JointLimit,
    JointTransform,
    JointVelocity,
    KinematicChain,
    Quaternion,
    RootDynamicLimit,
    SegmentDefinition,
    Vector3,
    project_body_pose_from_dof,
    project_joint_dof_rotation,
    quaternion_equivalent,
)

NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def zero_velocity() -> JointVelocity:
    return JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))


def dynamic(axis: Axis) -> JointDynamicLimit:
    return JointDynamicLimit(axis, 2.0, 4.0, 8.0)


def root_dynamic() -> RootDynamicLimit:
    return RootDynamicLimit(2.0, 4.0, 8.0, 2.0, 4.0, 8.0, 1.0, 2.0)


def arm_joint() -> JointDefinition:
    return JointDefinition(
        "hand",
        "root",
        AnatomicalRegion.HAND,
        AnatomicalSide.RIGHT,
        transform(),
        (
            JointLimit(Axis.X, -1.0, 1.0, -0.5, 0.5, 0.0),
            JointLimit(Axis.Y, -1.0, 1.0, -0.5, 0.5, 0.0),
        ),
        (dynamic(Axis.X), dynamic(Axis.Y)),
    )


def physical_model(
    *,
    segment_com_fraction: float = 0.5,
    mass_fraction: float = 1.0,
    revision: int = 3,
    fingerprint: str | None = None,
) -> CanonicalBodyModel:
    end_effector = EndEffectorDefinition(
        "right_hand_effector",
        "hand",
        Vector3(0, 0, 0.1),
        Vector3(0, 0, 1),
        Vector3(0, 1, 0),
    )
    return CanonicalBodyModel(
        "yura.canonical.v1",
        (
            JointDefinition(
                "root",
                None,
                AnatomicalRegion.ROOT,
                AnatomicalSide.CENTER,
                transform(),
                (),
            ),
            arm_joint(),
        ),
        (
            SegmentDefinition(
                "right_arm",
                "root",
                "hand",
                0.4,
                mass_fraction,
                segment_com_fraction,
            ),
        ),
        ("hand",),
        (
            KinematicChain(
                "right_arm",
                ("root", "hand"),
                "hand",
                "right_hand_effector",
            ),
        ),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
        reference_height=1.6,
        body_model_revision=revision,
        body_model_fingerprint=fingerprint,
        end_effectors=(end_effector,),
        contact_points=(
            ContactPointDefinition("root_support", "root", Vector3(0, -0.8, 0), True),
        ),
        root_dynamic_limit=root_dynamic(),
    )


def dof_state(*, x: float = 0.0, y: float = 0.0) -> JointDofState:
    return JointDofState(
        "hand",
        (
            JointDofCoordinate(Axis.X, x, 0.0, 0.0),
            JointDofCoordinate(Axis.Y, y, 0.0, 0.0),
        ),
    )


def body_velocity() -> BodyVelocity:
    return BodyVelocity(zero_velocity(), (("hand", zero_velocity()),))


def test_scalar_dof_projection_uses_fixed_x_then_y_then_z_order() -> None:
    joint = JointDefinition(
        "hand",
        "root",
        AnatomicalRegion.HAND,
        AnatomicalSide.RIGHT,
        transform(),
        (
            JointLimit(Axis.X, -pi, pi, -pi / 2, pi / 2, 0.0),
            JointLimit(Axis.Y, -pi, pi, -pi / 2, pi / 2, 0.0),
        ),
        (dynamic(Axis.X), dynamic(Axis.Y)),
    )
    state = dof_state(x=pi / 2, y=pi / 2)

    rotation = project_joint_dof_rotation(joint, state)

    assert quaternion_equivalent(rotation, Quaternion(0.5, 0.5, 0.5, 0.5))


def test_quaternion_sign_is_same_rotation() -> None:
    value = Quaternion(0.5, 0.5, 0.5, 0.5)
    negated = Quaternion(-0.5, -0.5, -0.5, -0.5)

    assert quaternion_equivalent(value, negated)


def test_scalar_dof_hard_limit_uses_declared_axes_without_quaternion_decomposition() -> None:
    joint = arm_joint()
    dof_state(x=-1.0, y=1.0).validate_for(joint)

    with pytest.raises(ValueError, match="hard limit"):
        dof_state(x=1.0001).validate_for(joint)

    with pytest.raises(ValueError, match="exactly once"):
        JointDofState(
            "hand",
            (JointDofCoordinate(Axis.Z, 0.0, 0.0, 0.0),),
        ).validate_for(joint)


def test_model_fingerprint_is_stable_and_changes_with_physical_semantics() -> None:
    first = physical_model()
    same = physical_model()
    changed = physical_model(segment_com_fraction=0.6)

    assert first.body_model_fingerprint == same.body_model_fingerprint
    assert first.body_model_fingerprint != changed.body_model_fingerprint


def test_stale_supplied_fingerprint_is_rejected_at_physical_control_boundary() -> None:
    stale = physical_model(fingerprint="wrong-fingerprint")

    assert not stale.physical_control_contract_complete
    with pytest.raises(ValueError, match="不完全"):
        stale.require_physical_control_contract()


def test_mass_fraction_total_is_rejected_at_physical_control_boundary() -> None:
    bad_mass = physical_model(mass_fraction=0.8)

    assert not bad_mass.physical_control_contract_complete
    with pytest.raises(ValueError, match="不完全"):
        bad_mass.require_physical_control_contract()


def test_physical_control_contract_fails_closed_when_required_geometry_is_missing() -> None:
    legacy = CanonicalBodyModel(
        "legacy",
        (
            JointDefinition(
                "root",
                None,
                AnatomicalRegion.ROOT,
                AnatomicalSide.CENTER,
                transform(),
                (),
            ),
            JointDefinition(
                "hand",
                "root",
                AnatomicalRegion.HAND,
                AnatomicalSide.RIGHT,
                transform(),
                (JointLimit(Axis.X, -1.0, 1.0, -0.5, 0.5, 0.0),),
            ),
        ),
        (SegmentDefinition("arm", "root", "hand", 0.4, 1.0),),
        ("hand",),
        (KinematicChain("arm", ("root", "hand"), "hand"),),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
    )

    assert not legacy.physical_control_contract_complete
    with pytest.raises(ValueError, match="不完全"):
        legacy.require_physical_control_contract()


def test_end_effector_axes_are_explicit_unit_nonparallel_vectors() -> None:
    with pytest.raises(ValueError, match="単位"):
        EndEffectorDefinition(
            "hand",
            "hand",
            Vector3(0, 0, 0),
            Vector3(0, 0, 2),
            Vector3(0, 1, 0),
        )

    with pytest.raises(ValueError, match="平行"):
        EndEffectorDefinition(
            "hand",
            "hand",
            Vector3(0, 0, 0),
            Vector3(0, 0, 1),
            Vector3(0, 0, -1),
        )


def test_physical_body_state_binds_model_generation_and_scalar_dof_authority() -> None:
    canonical = physical_model()
    states = (dof_state(x=0.25, y=-0.2),)
    pose = project_body_pose_from_dof(canonical, transform(), states)
    state = BodyState(
        canonical.body_model_id,
        5,
        NOW,
        pose,
        body_velocity(),
        (),
        canonical.body_model_revision,
        canonical.body_model_fingerprint,
        states,
    )

    state.validate_physical_for(canonical)
    serialized = state.to_dict()
    assert serialized["body_model_revision"] == 3
    assert serialized["body_model_fingerprint"] == canonical.body_model_fingerprint


def test_physical_body_state_rejects_generation_mismatch_and_missing_scalar_state() -> None:
    canonical = physical_model()
    states = (dof_state(),)
    pose = project_body_pose_from_dof(canonical, transform(), states)

    wrong_generation = BodyState(
        canonical.body_model_id,
        1,
        NOW,
        pose,
        body_velocity(),
        (),
        canonical.body_model_revision + 1,
        canonical.body_model_fingerprint,
        states,
    )
    with pytest.raises(ValueError, match="revision"):
        wrong_generation.validate_physical_for(canonical)

    missing_scalar = BodyState(
        canonical.body_model_id,
        1,
        NOW,
        pose,
        body_velocity(),
        (),
        canonical.body_model_revision,
        canonical.body_model_fingerprint,
        (),
    )
    with pytest.raises(ValueError, match="scalar"):
        missing_scalar.validate_physical_for(canonical)
