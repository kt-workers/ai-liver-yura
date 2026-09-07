from __future__ import annotations

from datetime import datetime, timezone
from math import cos, sin

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
)
from app.domain.body_motion_planning import (
    BodyBalanceMode,
    BodySpatialTarget,
    BodySpatialTargetKind,
)
from app.domain.body_solver import (
    BodySolveTask,
    BodySolveTaskKind,
    BodySpatialTargetSnapshot,
    BodyTrajectoryPhase,
    ExecutableBodyTrajectory,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
SUPPORT_CONTACT_IDS = ("support:left", "support:right", "support:front")


def identity_transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def physical_model() -> CanonicalBodyModel:
    root = JointDefinition(
        "root",
        None,
        AnatomicalRegion.ROOT,
        AnatomicalSide.CENTER,
        identity_transform(),
        (),
    )
    arm = JointDefinition(
        "arm",
        "root",
        AnatomicalRegion.ARM,
        AnatomicalSide.RIGHT,
        identity_transform(),
        (JointLimit(Axis.Z, -1.2, 1.2, -0.8, 0.8, 0.0),),
        (JointDynamicLimit(Axis.Z, 1.5, 3.0, 12.0),),
    )
    return CanonicalBodyModel(
        "body.d10",
        (root, arm),
        (SegmentDefinition("segment:arm", "root", "arm", 1.0, 1.0, 0.0),),
        ("arm",),
        (
            KinematicChain(
                "chain:arm",
                ("root", "arm"),
                "arm",
                "effector:hand",
            ),
        ),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
        reference_height=1.0,
        end_effectors=(
            EndEffectorDefinition(
                "effector:hand",
                "arm",
                Vector3(1, 0, 0),
                Vector3(1, 0, 0),
                Vector3(0, 1, 0),
            ),
        ),
        contact_points=(
            ContactPointDefinition(
                "support:left", "root", Vector3(-0.4, 0, -0.4), True
            ),
            ContactPointDefinition(
                "support:right", "root", Vector3(0.4, 0, -0.4), True
            ),
            ContactPointDefinition(
                "support:front", "root", Vector3(0, 0, 0.4), True
            ),
        ),
        root_dynamic_limit=RootDynamicLimit(
            max_linear_velocity_mps=2.0,
            max_linear_acceleration_mps2=4.0,
            max_linear_jerk_mps3=12.0,
            max_angular_velocity_radps=3.0,
            max_angular_acceleration_radps2=6.0,
            max_angular_jerk_radps3=18.0,
            directional_translation_budget_m=0.5,
            impulse_budget_mps=1.0,
        ),
    )


def physical_state(*, revision: int = 0, angle: float = 0.0) -> BodyState:
    model = physical_model()
    dof_states = (
        JointDofState(
            "arm",
            (JointDofCoordinate(Axis.Z, angle, 0.0, 0.0),),
        ),
    )
    root = identity_transform()
    pose = project_body_pose_from_dof(model, root, dof_states)
    zero = JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))
    fingerprint = model.body_model_fingerprint
    assert fingerprint is not None
    return BodyState(
        model.body_model_id,
        revision,
        NOW,
        pose,
        BodyVelocity(zero, (("arm", zero),)),
        body_model_revision=model.body_model_revision,
        body_model_fingerprint=fingerprint,
        joint_dof_states=dof_states,
    )


class StaticTargetResolver:
    def __init__(self, snapshots: tuple[BodySpatialTargetSnapshot, ...]) -> None:
        self._snapshots = {item.target_ref: item for item in snapshots}

    def resolve(self, target_ref: str) -> BodySpatialTargetSnapshot | None:
        return self._snapshots.get(target_ref)

    def replace(self, snapshot: BodySpatialTargetSnapshot) -> None:
        self._snapshots[snapshot.target_ref] = snapshot


def position_snapshot(
    angle: float,
    *,
    target_ref: str = "target:hand",
    generation: int = 1,
) -> BodySpatialTargetSnapshot:
    return BodySpatialTargetSnapshot(
        target_ref,
        Vector3(cos(angle), sin(angle), 0),
        None,
        None,
        "test.geometry",
        "geometry:hand",
        1,
        generation,
        NOW,
    )


def reach_task(
    *,
    extent: float = 1.0,
    target_ref: str = "target:hand",
) -> BodySolveTask:
    return BodySolveTask(
        "goal:reach",
        BodySolveTaskKind.POSITION_TARGET,
        ("arm", "root"),
        ("chain:arm",),
        BodySpatialTarget(
            BodySpatialTargetKind.TARGET_REF,
            None,
            target_ref,
            extent,
        ),
        1.0,
    )


def trajectory_for(
    task: BodySolveTask,
    *,
    trajectory_id: str = "trajectory:d10",
    plan_id: str = "plan:d10",
    solver_policy_revision: int = 1,
    start_body_state_revision: int = 0,
    duration_s: float = 0.5,
    balance_mode: BodyBalanceMode = BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
) -> ExecutableBodyTrajectory:
    model = physical_model()
    fingerprint = model.body_model_fingerprint
    assert fingerprint is not None
    return ExecutableBodyTrajectory(
        trajectory_id,
        plan_id,
        model.body_model_id,
        model.body_model_revision,
        fingerprint,
        solver_policy_revision,
        start_body_state_revision,
        task.joint_ids,
        task.chain_ids,
        (BodyTrajectoryPhase("phase:main", 0.0, duration_s, (task,), balance_mode),),
    )
