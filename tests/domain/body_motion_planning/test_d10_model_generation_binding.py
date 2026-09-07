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
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionContext,
    BodyFocusExpressionConstraint,
    NormalizedExpressionValue,
)
from app.domain.body_motion_planning import (
    BodyBalanceMode,
    BodyMotionConstraintKind,
    BodyMotionConstraintView,
    BodyMotionEffect,
    BodyMotionGoal,
    BodyMotionIntentView,
    BodyMotionPhase,
    BodyMotionPlanAuthority,
    BodyMotionPlanCandidate,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    BodyMotionSelector,
    BodySpatialTarget,
    BodySpatialTargetKind,
)
from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    PreconditionRef,
    RevisionVector,
)
from app.domain.executive import ExecutiveInterruptibility, ExecutivePriority

NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)
REVISIONS = RevisionVector(7, 5, 3)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _joint_velocity() -> JointVelocity:
    return JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))


def _model(*, revision: int = 3, reference_height: float = 1.0) -> CanonicalBodyModel:
    root = JointDefinition(
        "root",
        None,
        AnatomicalRegion.ROOT,
        AnatomicalSide.CENTER,
        _transform(),
        (),
    )
    hand = JointDefinition(
        "right_hand",
        "root",
        AnatomicalRegion.HAND,
        AnatomicalSide.RIGHT,
        _transform(),
        (JointLimit(Axis.Z, -1.0, 1.0, -0.5, 0.5, 0.0),),
    )
    return CanonicalBodyModel(
        "body.v1",
        (root, hand),
        (SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1.0),),
        ("right_hand",),
        (KinematicChain("right_arm", ("root", "right_hand"), "right_hand"),),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
        reference_height,
        revision,
    )


def _state(model: CanonicalBodyModel, *, revision: int = 2) -> BodyState:
    pose = BodyPose(_transform(), (("right_hand", _transform()),))
    velocity = BodyVelocity(_joint_velocity(), (("right_hand", _joint_velocity()),))
    return BodyState(
        model.body_model_id,
        revision,
        NOW,
        pose,
        velocity,
        (),
        model.body_model_revision,
        model.body_model_fingerprint,
    )


def _expression(revision: int = 4) -> BodyExpressionContext:
    return BodyExpressionContext(
        revision,
        7,
        2,
        7,
        3,
        7,
        "generic",
        1,
        1,
        "policy",
        1,
        tuple(
            BodyExpressionAxisValue(axis, NormalizedExpressionValue(0.0))
            for axis in BodyExpressionAxis
        ),
        BodyFocusExpressionConstraint(None, None, (), None, None),
        (),
        (),
        (),
        NOW,
    )


def _constraint() -> BodyMotionConstraintView:
    return BodyMotionConstraintView(
        "constraint:1",
        BodyMotionConstraintKind.ENVIRONMENT,
        "environment",
        "zone:1",
        1,
        "trusted boundary",
        ("body:1",),
    )


def _intent() -> BodyMotionIntentView:
    return BodyMotionIntentView(
        "decision:1",
        "intent:1",
        "右手を対象へ向ける",
        "motion:reach",
        "target:1",
        ("constraint:1",),
        ("event:1",),
        REVISIONS,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (PreconditionRef("pre:1", "ready", "body", True),),
        (CapabilityRequirement("body", "motion"),),
    )


def _capabilities() -> tuple[CapabilityDescriptor, ...]:
    return (
        CapabilityDescriptor(
            "cap:1",
            "body",
            ("motion",),
            CapabilityAvailability.AVAILABLE,
            1,
            {},
        ),
    )


def _snapshot(model: CanonicalBodyModel) -> BodyMotionPlanningContextSnapshot:
    return BodyMotionPlanningContextSnapshot(
        "request:1",
        _intent(),
        model,
        _state(model),
        _expression(),
        (_constraint(),),
        _capabilities(),
        NOW,
        "trace:1",
    )


def _candidate(model: CanonicalBodyModel) -> BodyMotionPlanCandidate:
    goal = BodyMotionGoal(
        "goal:1",
        BodyMotionEffect.TRANSLATE,
        BodyMotionSelector(
            AnatomicalRegion.HAND,
            AnatomicalSide.RIGHT,
            ("right_arm",),
            ("right_hand",),
        ),
        BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:1", 0.5),
        0.5,
        ("constraint:1",),
    )
    return BodyMotionPlanCandidate(
        "candidate:1",
        "request:1",
        "decision:1",
        "intent:1",
        REVISIONS,
        model.body_model_id,
        2,
        4,
        (_constraint(),),
        (goal,),
        (
            BodyMotionPhase(
                "phase:1",
                ("goal:1",),
                1.0,
                BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
            ),
        ),
        (),
        (),
        NOW,
    )


def _current(
    model: CanonicalBodyModel,
    *,
    body_state_revision: int = 2,
    expression_revision: int = 4,
) -> BodyMotionPlanningCommitState:
    return BodyMotionPlanningCommitState(
        REVISIONS,
        _intent(),
        model,
        _state(model, revision=body_state_revision),
        _expression(expression_revision),
        (_constraint(),),
        _capabilities(),
        (PreconditionRef("pre:1", "ready", "body", True),),
        NOW,
    )


def test_plan_binds_exact_body_model_generation() -> None:
    model = _model()
    fingerprint = model.body_model_fingerprint
    assert fingerprint is not None

    plan = BodyMotionPlanAuthority().commit(
        _candidate(model),
        _snapshot(model),
        _current(model),
        plan_id="plan:1",
        committed_at=NOW,
    )

    assert plan.body_model_id == model.body_model_id
    assert plan.body_model_revision == model.body_model_revision
    assert plan.body_model_fingerprint == fingerprint


def test_model_revision_drift_is_hard_stale_even_when_id_is_unchanged() -> None:
    captured = _model(revision=3)
    current = _model(revision=4)
    assert captured.body_model_id == current.body_model_id
    assert captured.body_model_fingerprint == current.body_model_fingerprint

    with pytest.raises(ValueError, match="body model"):
        BodyMotionPlanAuthority().commit(
            _candidate(captured),
            _snapshot(captured),
            _current(current),
            plan_id="plan:1",
            committed_at=NOW,
        )


def test_model_fingerprint_drift_is_hard_stale() -> None:
    captured = _model(revision=3, reference_height=1.0)
    current = _model(revision=3, reference_height=1.1)
    assert captured.body_model_id == current.body_model_id
    assert captured.body_model_revision == current.body_model_revision
    assert captured.body_model_fingerprint != current.body_model_fingerprint

    with pytest.raises(ValueError, match="body model"):
        BodyMotionPlanAuthority().commit(
            _candidate(captured),
            _snapshot(captured),
            _current(current),
            plan_id="plan:1",
            committed_at=NOW,
        )


def test_rebaseable_revisions_preserve_model_binding() -> None:
    model = _model()
    plan = BodyMotionPlanAuthority().commit(
        _candidate(model),
        _snapshot(model),
        _current(model, body_state_revision=9, expression_revision=8),
        plan_id="plan:1",
        committed_at=NOW,
    )

    assert plan.candidate.planning_body_state_revision == 2
    assert plan.candidate.planning_expression_revision == 4
    assert plan.body_model_revision == model.body_model_revision
    assert plan.body_model_fingerprint == model.body_model_fingerprint
