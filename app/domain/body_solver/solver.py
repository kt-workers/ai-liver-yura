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
    project_body_pose_from_dof,
)

from .contracts import BodySolveTask, BodySolveTaskKind, BodySolverError, BodySolverFailureCode
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


def _rotate_forward(rotation: object) -> tuple[float, float, float]:
    from app.domain.body import Quaternion

    if not isinstance(rotation, Quaternion):
        raise BodySolverError(BodySolverFailureCode.NUMERICAL_FAILURE)
    x = 2.0 * (rotation.x * rotation.z + rotation.w * rotation.y)
    y = 2.0 * (rotation.y * rotation.z - rotation.w * rotation.x)
    z = 1.0 - 2.0 * (rotation.x * rotation.x + rotation.y * rotation.y)
    magnitude = sqrt(x * x + y * y + z * z)
    if magnitude == 0:
        raise BodySolverError(BodySolverFailureCode.NUMERICAL_FAILURE)
    return x / magnitude, y / magnitude, z / magnitude


def _residuals(
    model: CanonicalBodyModel,
    pose: BodyPose,
    tasks: tuple[BodySolveTask, ...],
    targets: dict[str, ResolvedBodyTaskTarget],
) -> tuple[BodyTaskResidual, ...]:
    result: list[BodyTaskResidual] = []
    for task in tasks:
        target = targets.get(task.goal_id)
        if target is None:
            raise BodySolverError(BodySolverFailureCode.INFEASIBLE_TARGET)
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
            desired = _rotate_forward(target.orientation)
            actual_magnitude = frame.forward_axis.magnitude
            if actual_magnitude == 0:
                raise BodySolverError(BodySolverFailureCode.NUMERICAL_FAILURE)
            actual = (
                frame.forward_axis.x / actual_magnitude,
                frame.forward_axis.y / actual_magnitude,
                frame.forward_axis.z / actual_magnitude,
            )
            dot = max(-1.0, min(1.0, actual[0] * desired[0] + actual[1] * desired[1] + actual[2] * desired[2]))
            orientation_error = acos(dot)
        result.append(
            BodyTaskResidual(
                task.goal_id,
                position_error,
                orientation_error,
            )
        )
    return tuple(result)


def _objective(
    residuals: tuple[BodyTaskResidual, ...],
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
    return value


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


def _state_map(states: tuple[JointDofState, ...]) -> dict[tuple[str, Axis], JointDofCoordinate]:
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
                position_radians if coordinate.axis is axis else coordinate.position_radians,
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
            (joint_id, coordinate.axis)
            for joint_id, state_item in ((item.joint_id, item) for item in current)
            if joint_id in relevant_joint_ids
            for coordinate in state_item.coordinates
        ),
        key=lambda item: (item[0], item[1].value),
    )
    if not coordinate_keys and any(
        task.kind is not BodySolveTaskKind.ROOT_IMPULSE_TARGET for task in tasks
    ):
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)

    pose = project_body_pose_from_dof(model, state.pose.root_world_transform, current)
    residuals = _residuals(model, pose, tasks, target_by_goal)
    if _within_tolerance(residuals, model, policy):
        return BodyIKSolution(BodySolveFeasibility.FEASIBLE, current, pose, 0, residuals)

    iterations = 0
    for iteration in range(policy.max_ik_iterations):
        iterations = iteration + 1
        step = policy.max_per_iteration_dof_step_radians * (0.5 ** (iteration // 8))
        improved = False
        baseline_residuals = _residuals(model, pose, tasks, target_by_goal)
        baseline_objective = _objective(baseline_residuals, model, policy)
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
                    min(limit.hard_max_radians, coordinate.position_radians + direction * step),
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
                    _residuals(model, candidate_pose, tasks, target_by_goal),
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
        residuals = _residuals(model, pose, tasks, target_by_goal)
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

    residuals = _residuals(model, pose, tasks, target_by_goal)
    return BodyIKSolution(
        BodySolveFeasibility.INFEASIBLE,
        tuple(state.joint_dof_states),
        state.pose,
        iterations,
        residuals,
    )
