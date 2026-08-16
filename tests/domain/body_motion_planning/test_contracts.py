from __future__ import annotations

from dataclasses import replace
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

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)
REVISIONS = RevisionVector(7, 5, 3)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _model() -> CanonicalBodyModel:
    root = JointDefinition(
        "root",
        None,
        AnatomicalRegion.ROOT,
        AnatomicalSide.CENTER,
        _transform(),
        (JointLimit(Axis.Z, -1, 1, -0.5, 0.5, 0),),
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
        (SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1.0),),
        ("right_hand",),
        (KinematicChain("right_arm", ("root", "right_hand"), "right_hand"),),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
    )


def _state() -> BodyState:
    pose = BodyPose(_transform(), (("right_hand", _transform()),))
    velocity = BodyVelocity(
        JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0)),
        (("right_hand", JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))),),
    )
    return BodyState("body.v1", 2, NOW, pose, velocity)


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


def _constraint(revision: int = 1) -> BodyMotionConstraintView:
    return BodyMotionConstraintView(
        "constraint:1",
        BodyMotionConstraintKind.ENVIRONMENT,
        "environment",
        "zone:1",
        revision,
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


def _snapshot() -> BodyMotionPlanningContextSnapshot:
    return BodyMotionPlanningContextSnapshot(
        "request:1",
        _intent(),
        _model(),
        _state(),
        _expression(),
        (_constraint(),),
        NOW,
        "trace:1",
    )


def _goal(effect: BodyMotionEffect = BodyMotionEffect.TRANSLATE) -> BodyMotionGoal:
    target = BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:1", 0.5)
    if effect is BodyMotionEffect.IMPULSE:
        target = BodySpatialTarget(BodySpatialTargetKind.DIRECTION, Vector3(0, 1, 0), None, 0.5)
    return BodyMotionGoal(
        "goal:1",
        effect,
        BodyMotionSelector(
            AnatomicalRegion.HAND, AnatomicalSide.RIGHT, ("right_arm",), ("right_hand",)
        ),
        target,
        0.5,
        ("constraint:1",),
    )


def _candidate() -> BodyMotionPlanCandidate:
    goal = _goal()
    return BodyMotionPlanCandidate(
        "candidate:1",
        "request:1",
        "decision:1",
        "intent:1",
        REVISIONS,
        "body.v1",
        2,
        4,
        (_constraint(),),
        (goal,),
        (BodyMotionPhase("phase:1", ("goal:1",), 1.0, BodyBalanceMode.STABLE_SUPPORT_REQUIRED),),
        (),
        (),
        NOW,
    )


def _current() -> BodyMotionPlanningCommitState:
    return BodyMotionPlanningCommitState(
        REVISIONS,
        _intent(),
        _model(),
        _state(),
        _expression(),
        (_constraint(),),
        (
            CapabilityDescriptor(
                "cap:1", "body", ("motion",), CapabilityAvailability.AVAILABLE, 1, {}
            ),
        ),
        (PreconditionRef("pre:1", "ready", "body", True),),
        NOW,
    )


@pytest.mark.parametrize(
    "direction",
    [
        Vector3(1, 0, 0),
        Vector3(-1, 0, 0),
        Vector3(0, 1, 0),
        Vector3(0, -1, 0),
        Vector3(0, 0, 1),
        Vector3(0, 0, -1),
    ],
)
def test_direction_accepts_canonical_six_axes(direction: Vector3) -> None:
    assert (
        BodySpatialTarget(BodySpatialTargetKind.DIRECTION, direction, None, 0.5).direction
        == direction
    )


@pytest.mark.parametrize("direction", (Vector3(0, 0, 0), Vector3(1, 1, 0)))
def test_direction_rejects_zero_or_non_unit(direction: Vector3) -> None:
    with pytest.raises(ValueError):
        BodySpatialTarget(BodySpatialTargetKind.DIRECTION, direction, None, 0.5)


def test_contact_and_impulse_structural_invariants_are_fail_closed() -> None:
    with pytest.raises(ValueError):
        BodyMotionGoal(
            "contact",
            BodyMotionEffect.CONTACT,
            BodyMotionSelector(AnatomicalRegion.HAND),
            BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:1", 0.5),
            0.5,
        )
    with pytest.raises(ValueError):
        BodyMotionGoal(
            "impulse",
            BodyMotionEffect.IMPULSE,
            BodyMotionSelector(AnatomicalRegion.ROOT),
            BodySpatialTarget(BodySpatialTargetKind.DIRECTION, Vector3(0, 1, 0), None, 0.5),
            0.0,
        )


def test_snapshot_requires_exact_constraint_grounding() -> None:
    with pytest.raises(ValueError):
        replace(_snapshot(), constraints=())


def test_authority_accepts_body_state_and_expression_revision_advance() -> None:
    authority = BodyMotionPlanAuthority()
    plan = authority.commit(
        _candidate(),
        _snapshot(),
        replace(_current(), body_state=replace(_state(), revision=3), expression=_expression(5)),
        plan_id="plan:1",
        committed_at=NOW,
    )
    assert plan.candidate.planning_body_state_revision == 2
    assert plan.candidate.planning_expression_revision == 4


@pytest.mark.parametrize(
    "current",
    [
        replace(_current(), revisions=RevisionVector(8, 5, 3)),
        replace(_current(), revisions=RevisionVector(7, 6, 3)),
        replace(_current(), revisions=RevisionVector(7, 5, 4)),
        replace(_current(), active_intent=None),
        replace(_current(), constraints=(_constraint(2),)),
    ],
)
def test_authority_rejects_hard_stale_sources(current: BodyMotionPlanningCommitState) -> None:
    with pytest.raises(ValueError):
        BodyMotionPlanAuthority().commit(
            _candidate(), _snapshot(), current, plan_id="plan:1", committed_at=NOW
        )


def test_authority_rejects_contact_target_outside_executive_authority() -> None:
    contact = BodyMotionGoal(
        "goal:1",
        BodyMotionEffect.CONTACT,
        BodyMotionSelector(AnatomicalRegion.HAND, AnatomicalSide.RIGHT, (), ("right_hand",)),
        BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:2", 0.5),
        0.5,
        ("constraint:1",),
    )
    candidate = replace(
        _candidate(),
        goals=(contact,),
        phases=(
            BodyMotionPhase("phase:1", ("goal:1",), 1.0, BodyBalanceMode.STABLE_SUPPORT_REQUIRED),
        ),
    )
    with pytest.raises(ValueError):
        BodyMotionPlanAuthority().commit(
            candidate, _snapshot(), _current(), plan_id="plan:1", committed_at=NOW
        )
