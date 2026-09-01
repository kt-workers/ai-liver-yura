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
    JointDefinition,
    JointLimit,
    JointTransform,
    JointVelocity,
    KinematicChain,
    Quaternion,
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
from app.domain.body_solver import BodySolveTaskKind, compile_body_motion_plan
from app.domain.contracts import RevisionVector
from app.domain.executive import ExecutiveInterruptibility, ExecutivePriority

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


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
    )
    return CanonicalBodyModel(
        "body.v1",
        (root, hand),
        (SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1),),
        ("right_hand",),
        (KinematicChain("right_arm", ("root", "right_hand"), "right_hand"),),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
    )


def _state(revision: int = 2) -> BodyState:
    transform = _transform()
    velocity = JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))
    return BodyState(
        "body.v1",
        revision,
        NOW,
        BodyPose(transform, (("right_hand", transform),)),
        BodyVelocity(velocity, (("right_hand", velocity),)),
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
    trajectory = compile_body_motion_plan(
        _plan(), _model(), _state(5), trajectory_id="trajectory:1", duration_s=2
    )
    assert trajectory.start_body_state_revision == 5
    assert trajectory.involved_joint_ids == ("right_hand", "root")
    assert trajectory.phases[0].end_offset_s == 2
    assert trajectory.phases[0].tasks[0].kind is BodySolveTaskKind.POSITION_TARGET


def test_compiler_rejects_model_mismatch() -> None:
    with pytest.raises(ValueError, match="身体モデル"):
        compile_body_motion_plan(
            _plan("other.v1"), _model(), _state(), trajectory_id="trajectory:1", duration_s=2
        )


def test_compiler_rejects_body_state_older_than_plan() -> None:
    with pytest.raises(ValueError, match="古く"):
        compile_body_motion_plan(
            _plan(), _model(), _state(1), trajectory_id="trajectory:1", duration_s=2
        )
