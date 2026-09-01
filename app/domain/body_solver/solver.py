from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import acos, sqrt

from app.domain.body import (
    Axis,
    BodyPose,
    BodyState,
    CanonicalBodyModel,
    JointDofCoordinate,
    JointDofState,
    Quaternion,
    project_body_pose_from_dof,
)

from .contracts import (
    BodySolverError,
    BodySolverFailureCode,
    BodySolveTask,
    BodySolveTaskKind,
)
from .physical import end_effector_world_frame
from .policy import BodySolverPolicy
from .targets import ResolvedBodyTaskTarget


class BodySolveFeasibility(str, Enum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True, slots=True)
class BodyTaskResidual:
    goal_id: str
    position_error_m: float | None
    orientation_error_radians: float | None
    linear_velocity_error_mps: float | None = None


@dataclass(frozen=True, slots=True)
class BodyIKSolution:
    feasibility: BodySolveFeasibility
    joint_dof_states: tuple[JointDofState, ...]
    pose: BodyPose
    iterations: int
    residuals: tuple[BodyTaskResidual, ...]


def _task_end_effector_id(task: BodySolveTask, model: CanonicalBodyModel) -> str:
    if len(task.chain_ids) == 1:
        chain = next(
            (item for item in model.kinematic_chains if item.chain_id == task.chain_ids[0]),
            None,
        )
        if chain is None or chain.end_effector_id is None:
            raise BodySolverError(BodySolverFailureCode.UNKNOWN_BODY_REFERENCE)
        return chain.end_effector_id
    matching = [
        item.end_effector_id
        for item in model.end_effectors
        if item.joint_id in task.joint_ids
    ]
    if len(matching) != 1:
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
    return matching[0]


def _quaternion_distance(left: Quaternion, right: Quaternion) -> float:
    dot = abs(
        left.x * right.x
        + left.y * right.y
        + left.z * right.z
        + left.w * right.w
    )
    return 2.0 * acos(max(-1.0, min(1.0, dot)))


def evaluate_body_task_residuals(
    model: CanonicalBodyModel,
    pose: BodyPose,
    tasks: tuple[BodySolveTask, ...],
    targets: tuple[ResolvedBodyTaskTarget, ...],
) -> tuple[BodyTaskResidual, ...]:
    target_by_goal = {item.goal_id: item for item in targets}
    if set(target_by_goal) != {item.goal_id for item in tasks}:
        raise BodySolverError(BodySolverFailureCode.INFEASIBLE_TARGET)
    result: list[BodyTaskResidual] = []
    for task in tasks:
        target = target_by_goal[task.goal_id]
        if task.kind is BodySolveTaskKind.ROOT_IMPULSE_TARGET:
            result.append(BodyTaskResidual(task.goal_id, None, None))
            continue
        frame = end_effector_world_frame(model, pose, _task_end_effector_id(task, model))
        position_error: float | None = None
        orientation_error: float | None = None
        if target.position is not None:
            dx = target.position.x - frame.position.x
            dy = target.position.y - frame.position.y
            dz = target.position.z - frame.position.z
            position_error = sqrt(dx * dx + dy * dy + dz * dz)
        if target.orientation is not None:
            orientation_error = _quaternion_distance(frame.orientation, target.orientation)
        result.append(BodyTaskResidual(task.goal_id, position_error, orientation_error))
    return tuple(result)


def _comfort_penalty(
    states: tuple[JointDofState, ...],
    model: CanonicalBodyModel,
) -> float:
    definitions = {item.joint_id: item for item in model.joints}
    penalty = 0.0
    for state in states:
        definition = definitions[state.joint_id]
        limits = {item.axis: item for item in definition.limits}
        for coordinate in state.coordinates:
            limit = limits[coordinate.axis]
            hard_span = max(limit.hard_max_radians - limit.hard_min_radians, 1e-12)
            if coordinate.position_radians < limit.comfortable_min_radians:
                distance = limit.comfortable_min_radians - coordinate.position_radians
            elif coordinate.position_radians > limit.comfortable_max_radians:
                distance = coordinate.position_radians - limit.comfortable_max_radians
            else:
                distance = 0.1 * abs(coordinate.position_radians - limit.relaxed_radians)
            penalty += (distance / hard_span) ** 2
    return penalty


def _objective(
    residuals: tuple[BodyTaskResidual, ...],
    states: tuple[JointDofState, ...],
    model: CanonicalBodyModel,
    policy: BodySolverPolicy,
) -> float:
    position_tolerance = policy.position_tolerance_m(model.reference_height)
    value = 0.0
    for residual in residuals:
        if residual.position_error_m is not None:
            value += (residual.position_error_m / position_tolerance) ** 2
        if residual.orientation_error_radians is not None:
            value += (
                residual.orientation_error_radians
                / policy.orientation_residual_tolerance_radians
            ) ** 2
    return value + 1e-9 * _comfort_penalty(states, model)


def _within_tolerance(
    residuals: tuple[BodyTaskResidual, ...],
    model: CanonicalBodyModel,
    policy: BodySolverPolicy,
) -> bool:
    position_tolerance = policy.position_tolerance_m(model.reference_height)
    return all(
        (item.position_error_m is None or item.position_error_m <= position_tolerance)
        and (
            item.orientation_error_radians is None
            or item.orientation_error_radians <= policy.orientation_residual_tolerance_radians
        )
        for item in residuals
    )


def _state_map(
    states: tuple[JointDofState, ...],
) -> dict[tuple[str, Axis], JointDofCoordinate]:
    return {
        (state.joint_id, coordinate.axis): coordinate
        for state in states
        for coordinate in state.coordinates
    }


def _replace_coordinate(
    states: tuple[JointDofState, ...],
    joint_id: str,
    axis: Axis,
    position_radians: float,
) -> tuple[JointDofState, ...]:
    updated: list[JointDofState] = []
    for state in states:
        if state.joint_id != joint_id:
            updated.append(state)
            continue
        coordinates = tuple(
            JointDofCoordinate(
                coordinate.axis,
                position_radians
                if coordinate.axis is axis
                else coordinate.position_radians,
                coordinate.velocity_radians_per_second,
                coordinate.acceleration_radians_per_second2,
            )
            for coordinate in state.coordinates
        )
        updated.append(JointDofState(state.joint_id, coordinates))
    return tuple(updated)


def solve_body_tasks(
    model: CanonicalBodyModel,
    state: BodyState,
    tasks: tuple[BodySolveTask, ...],
    targets: tuple[ResolvedBodyTaskTarget, ...],
    policy: BodySolverPolicy,
) -> BodyIKSolution:
    """Scalar DOFだけを更新するbounded deterministic coordinate-descent IK。"""

    if not isinstance(policy, BodySolverPolicy):
        raise BodySolverError(BodySolverFailureCode.INVALID_SOLVER_POLICY)
    model.require_physical_control_contract()
    state.validate_physical_for(model)
    if not tasks:
        raise BodySolverError(BodySolverFailureCode.INVALID_PLAN)
    target_by_goal = {item.goal_id: item for item in targets}
    if set(target_by_goal) != {item.goal_id for item in tasks}:
        raise BodySolverError(BodySolverFailureCode.INFEASIBLE_TARGET)

    current = tuple(state.joint_dof_states)
    relevant_joint_ids = {
        joint_id
        for task in tasks
        if task.kind is not BodySolveTaskKind.ROOT_IMPULSE_TARGET
        for joint_id in task.joint_ids
    }
    definitions = {item.joint_id: item for item in model.joints}
    coordinate_keys = sorted(
        (
            (state_item.joint_id, coordinate.axis)
            for state_item in current
            if state_item.joint_id in relevant_joint_ids
            for coordinate in state_item.coordinates
        ),
        key=lambda item: (item[0], item[1].value),
    )
    if not coordinate_keys and any(
        task.kind is not BodySolveTaskKind.ROOT_IMPULSE_TARGET for task in tasks
    ):
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)

    pose = project_body_pose_from_dof(model, state.pose.root_world_transform, current)
    residuals = evaluate_body_task_residuals(model, pose, tasks, targets)
    if _within_tolerance(residuals, model, policy):
        return BodyIKSolution(
            BodySolveFeasibility.FEASIBLE,
            current,
            pose,
            0,
            residuals,
        )

    iterations = 0
    for iteration in range(policy.max_ik_iterations):
        iterations = iteration + 1
        step = policy.max_per_iteration_dof_step_radians * (0.5 ** (iteration // 8))
        improved = False
        baseline_residuals = evaluate_body_task_residuals(
            model,
            pose,
            tasks,
            targets,
        )
        baseline_objective = _objective(
            baseline_residuals,
            current,
            model,
            policy,
        )
        state_coordinates = _state_map(current)
        for joint_id, axis in coordinate_keys:
            coordinate = state_coordinates[(joint_id, axis)]
            definition = definitions[joint_id]
            limit = next(item for item in definition.limits if item.axis is axis)
            best_states = current
            best_pose = pose
            best_objective = baseline_objective
            for direction in (-1.0, 1.0):
                candidate_position = max(
                    limit.hard_min_radians,
                    min(
                        limit.hard_max_radians,
                        coordinate.position_radians + direction * step,
                    ),
                )
                if candidate_position == coordinate.position_radians:
                    continue
                candidate_states = _replace_coordinate(
                    current,
                    joint_id,
                    axis,
                    candidate_position,
                )
                candidate_pose = project_body_pose_from_dof(
                    model,
                    state.pose.root_world_transform,
                    candidate_states,
                )
                candidate_objective = _objective(
                    evaluate_body_task_residuals(
                        model,
                        candidate_pose,
                        tasks,
                        targets,
                    ),
                    candidate_states,
                    model,
                    policy,
                )
                if candidate_objective + policy.numeric_epsilon < best_objective:
                    best_states = candidate_states
                    best_pose = candidate_pose
                    best_objective = candidate_objective
            if best_states is not current:
                current = best_states
                pose = best_pose
                baseline_objective = best_objective
                state_coordinates = _state_map(current)
                improved = True
        residuals = evaluate_body_task_residuals(model, pose, tasks, targets)
        if _within_tolerance(residuals, model, policy):
            return BodyIKSolution(
                BodySolveFeasibility.FEASIBLE,
                current,
                pose,
                iterations,
                residuals,
            )
        if not improved:
            break

    residuals = evaluate_body_task_residuals(model, pose, tasks, targets)
    return BodyIKSolution(
        BodySolveFeasibility.INFEASIBLE,
        tuple(state.joint_dof_states),
        state.pose,
        iterations,
        residuals,
    )
