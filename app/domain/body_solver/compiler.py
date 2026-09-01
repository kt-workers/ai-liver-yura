from __future__ import annotations

from app.domain.body import BodyState, CanonicalBodyModel, JointDefinition, KinematicChain
from app.domain.body_motion_planning import BodyMotionEffect, BodyMotionGoal, BodyMotionPlan
from app.domain.contracts.common import require_identifier

from .contracts import (
    BodySolverError,
    BodySolverFailureCode,
    BodySolveTask,
    BodySolveTaskKind,
    BodyTrajectoryPhase,
    ExecutableBodyTrajectory,
)
from .policy import BodySolverPolicy


def compile_body_motion_plan(
    plan: BodyMotionPlan,
    body_model: CanonicalBodyModel,
    latest_body_state: BodyState,
    solver_policy: BodySolverPolicy,
    *,
    trajectory_id: str,
    duration_s: float,
) -> ExecutableBodyTrajectory:
    if not isinstance(plan, BodyMotionPlan):
        raise BodySolverError(BodySolverFailureCode.INVALID_PLAN)
    if not isinstance(body_model, CanonicalBodyModel):
        raise BodySolverError(BodySolverFailureCode.MODEL_MISMATCH)
    if not isinstance(latest_body_state, BodyState):
        raise BodySolverError(BodySolverFailureCode.INVALID_DOF_STATE)
    if not isinstance(solver_policy, BodySolverPolicy):
        raise BodySolverError(BodySolverFailureCode.INVALID_SOLVER_POLICY)
    require_identifier(trajectory_id, "trajectory_id")

    if plan.body_model_id != body_model.body_model_id:
        raise BodySolverError(BodySolverFailureCode.MODEL_MISMATCH)
    if plan.body_model_revision != body_model.body_model_revision:
        raise BodySolverError(BodySolverFailureCode.MODEL_REVISION_MISMATCH)
    if plan.body_model_fingerprint != body_model.body_model_fingerprint:
        raise BodySolverError(BodySolverFailureCode.MODEL_FINGERPRINT_MISMATCH)
    try:
        latest_body_state.validate_physical_for(body_model)
    except ValueError as error:
        raise BodySolverError(BodySolverFailureCode.INVALID_DOF_STATE) from error
    if latest_body_state.body_model_revision != body_model.body_model_revision:
        raise BodySolverError(BodySolverFailureCode.MODEL_REVISION_MISMATCH)
    if latest_body_state.body_model_fingerprint != body_model.body_model_fingerprint:
        raise BodySolverError(BodySolverFailureCode.MODEL_FINGERPRINT_MISMATCH)
    if latest_body_state.revision < plan.candidate.planning_body_state_revision:
        raise BodySolverError(
            BodySolverFailureCode.STALE_HARD_DEPENDENCY,
            "latest BodyState is older than planning state",
        )

    chains: dict[str, KinematicChain] = {
        chain.chain_id: chain for chain in body_model.kinematic_chains
    }
    goals = {goal.goal_id: goal for goal in plan.candidate.goals}
    weights = sum(phase.relative_duration_weight for phase in plan.candidate.phases)
    if type(duration_s) not in (int, float) or duration_s <= 0 or weights <= 0:
        raise BodySolverError(BodySolverFailureCode.INVALID_PLAN, "trajectory duration is invalid")

    phase_start = 0.0
    phases: list[BodyTrajectoryPhase] = []
    involved_joint_ids: set[str] = set()
    involved_chain_ids: set[str] = set()
    for phase in plan.candidate.phases:
        phase_end = phase_start + float(duration_s) * phase.relative_duration_weight / weights
        tasks = tuple(
            _task_for(goals[goal_id], chains, body_model.joints) for goal_id in phase.goal_ids
        )
        phases.append(
            BodyTrajectoryPhase(phase.phase_id, phase_start, phase_end, tasks, phase.balance_mode)
        )
        for task in tasks:
            involved_joint_ids.update(task.joint_ids)
            involved_chain_ids.update(task.chain_ids)
        phase_start = phase_end
    fingerprint = body_model.body_model_fingerprint
    if fingerprint is None:
        raise BodySolverError(BodySolverFailureCode.MODEL_FINGERPRINT_MISMATCH)
    return ExecutableBodyTrajectory(
        trajectory_id,
        plan.plan_id,
        body_model.body_model_id,
        body_model.body_model_revision,
        fingerprint,
        solver_policy.policy_revision,
        latest_body_state.revision,
        tuple(sorted(involved_joint_ids)),
        tuple(sorted(involved_chain_ids)),
        tuple(phases),
    )


def _task_for(
    goal: BodyMotionGoal,
    chains: dict[str, KinematicChain],
    joints: tuple[JointDefinition, ...],
) -> BodySolveTask:
    selector = goal.selector
    chain_ids = selector.chain_ids
    joint_ids = set(selector.end_effector_joint_ids)
    for chain_id in chain_ids:
        chain = chains.get(chain_id)
        if chain is None:
            raise BodySolverError(BodySolverFailureCode.UNKNOWN_BODY_REFERENCE)
        joint_ids.update(chain.joint_ids)
    if not joint_ids:
        joint_ids.update(
            joint.joint_id
            for joint in joints
            if (selector.region is None or joint.region is selector.region)
            and (selector.side is None or joint.side is selector.side)
        )
    if not joint_ids:
        raise BodySolverError(BodySolverFailureCode.UNKNOWN_BODY_REFERENCE)
    return BodySolveTask(
        goal.goal_id,
        _task_kind(goal.effect),
        tuple(sorted(joint_ids)),
        chain_ids,
        goal.spatial_target,
        goal.intensity,
    )


def _task_kind(effect: BodyMotionEffect) -> BodySolveTaskKind:
    mapping = {
        BodyMotionEffect.ORIENT: BodySolveTaskKind.ORIENTATION_TARGET,
        BodyMotionEffect.TRANSLATE: BodySolveTaskKind.POSITION_TARGET,
        BodyMotionEffect.CONTACT: BodySolveTaskKind.CONTACT_TARGET,
        BodyMotionEffect.IMPULSE: BodySolveTaskKind.ROOT_IMPULSE_TARGET,
    }
    return mapping[effect]
