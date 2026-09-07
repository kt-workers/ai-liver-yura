from datetime import datetime, timezone

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
)
from app.domain.body_motion_planning import (
    BodyBalanceMode,
    BodyMotionEffect,
    BodyMotionGoal,
    BodyMotionPhase,
    BodyMotionPlan,
    BodyMotionPlanCandidate,
    BodyMotionSelector,
    BodySpatialTarget,
    BodySpatialTargetKind,
)
from app.domain.body_motion_planning.contracts import _PLAN_PROOF
from app.domain.body_solver import (
    BodySolverError,
    BodySolverFailureCode,
    BodySolveTaskKind,
    compile_body_motion_plan,
    v2_baseline_body_solver_policy,
)
from app.domain.contracts import RevisionVector
from app.domain.executive import ExecutiveInterruptibility, ExecutivePriority

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _root_dynamic_limit() -> RootDynamicLimit:
    return RootDynamicLimit(
        max_linear_velocity_mps=2.0,
        max_linear_acceleration_mps2=4.0,
        max_linear_jerk_mps3=12.0,
        max_angular_velocity_radps=3.0,
        max_angular_acceleration_radps2=6.0,
        max_angular_jerk_radps3=18.0,
        directional_translation_budget_m=0.5,
        impulse_budget_mps=1.0,
    )


def _model() -> CanonicalBodyModel:
    root = JointDefinition(
        "root", None, AnatomicalRegion.ROOT, AnatomicalSide.CENTER, _transform(), ()
    )
    hand = JointDefinition(
        "right_hand",
        "root",
        AnatomicalRegion.HAND,
        AnatomicalSide.RIGHT,
        _transform(),
        (JointLimit(Axis.Z, -1, 1, -0.5, 0.5, 0),),
        (JointDynamicLimit(Axis.Z, 2.0, 4.0, 12.0),),
    )
    return CanonicalBodyModel(
        "body.v1",
        (root, hand),
        (SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1, 0.5),),
        ("right_hand",),
        (
            KinematicChain(
                "right_arm",
                ("root", "right_hand"),
                "right_hand",
                "right_hand_effector",
            ),
        ),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
        end_effectors=(
            EndEffectorDefinition(
                "right_hand_effector",
                "right_hand",
                Vector3(0, 0, 0),
                Vector3(0, 0, 1),
                Vector3(0, 1, 0),
            ),
        ),
        root_dynamic_limit=_root_dynamic_limit(),
    )


def _state(revision: int = 2) -> BodyState:
    model = _model()
    transform = _transform()
    velocity = JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))
    fingerprint = model.body_model_fingerprint
    assert fingerprint is not None
    return BodyState(
        "body.v1",
        revision,
        NOW,
        BodyPose(transform, (("right_hand", transform),)),
        BodyVelocity(velocity, (("right_hand", velocity),)),
        body_model_revision=model.body_model_revision,
        body_model_fingerprint=fingerprint,
        joint_dof_states=(
            JointDofState(
                "right_hand",
                (JointDofCoordinate(Axis.Z, 0.0, 0.0, 0.0),),
            ),
        ),
    )


def _plan(model_id: str = "body.v1") -> BodyMotionPlan:
    goal = BodyMotionGoal(
        "goal:reach",
        BodyMotionEffect.TRANSLATE,
        BodyMotionSelector(None, None, ("right_arm",), ("right_hand",)),
        BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:1", 0.5),
        0.5,
    )
    candidate = BodyMotionPlanCandidate(
        "candidate:1",
        "request:1",
        "decision:1",
        "intent:1",
        RevisionVector(1, 1, 1),
        model_id,
        2,
        1,
        (),
        (goal,),
        (
            BodyMotionPhase(
                "phase:reach", ("goal:reach",), 1, BodyBalanceMode.STABLE_SUPPORT_REQUIRED
            ),
        ),
        (),
        (),
        NOW,
    )
    model = _model()
    fingerprint = model.body_model_fingerprint
    assert fingerprint is not None
    return BodyMotionPlan(
        "plan:1",
        candidate,
        "motion:1",
        ExecutivePriority.NORMAL,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (),
        (),
        model_id,
        model.body_model_revision,
        fingerprint,
        NOW,
        _proof=_PLAN_PROOF,
    )


def test_compiler_resolves_canonical_chain_and_rebases_to_latest_state() -> None:
    policy = v2_baseline_body_solver_policy()
    trajectory = compile_body_motion_plan(
        _plan(),
        _model(),
        _state(5),
        policy,
        trajectory_id="trajectory:1",
        duration_s=2,
    )
    assert trajectory.start_body_state_revision == 5
    assert trajectory.body_model_revision == 0
    assert trajectory.solver_policy_revision == policy.policy_revision
    assert trajectory.involved_joint_ids == ("right_hand", "root")
    assert trajectory.phases[0].end_offset_s == 2
    assert trajectory.phases[0].tasks[0].kind is BodySolveTaskKind.POSITION_TARGET


def test_compiler_rejects_model_mismatch() -> None:
    with pytest.raises(BodySolverError) as error:
        compile_body_motion_plan(
            _plan("other.v1"),
            _model(),
            _state(),
            v2_baseline_body_solver_policy(),
            trajectory_id="trajectory:1",
            duration_s=2,
        )
    assert error.value.code is BodySolverFailureCode.MODEL_MISMATCH


def test_compiler_rejects_body_state_older_than_plan() -> None:
    with pytest.raises(BodySolverError) as error:
        compile_body_motion_plan(
            _plan(),
            _model(),
            _state(1),
            v2_baseline_body_solver_policy(),
            trajectory_id="trajectory:1",
            duration_s=2,
        )
    assert error.value.code is BodySolverFailureCode.STALE_HARD_DEPENDENCY
