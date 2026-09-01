from __future__ import annotations

from dataclasses import dataclass
from math import acos, cos, sin, sqrt

from app.domain.body import (
    Axis,
    BodyState,
    BodyVelocity,
    CanonicalBodyModel,
    JointDofCoordinate,
    JointDofState,
    JointDynamicLimit,
    JointTransform,
    JointVelocity,
    Quaternion,
    Vector3,
)
from app.domain.body_motion_planning import BodyBalanceMode

from .contracts import BodySolverError, BodySolverFailureCode


@dataclass(frozen=True, slots=True)
class RootDynamicsState:
    linear_acceleration: Vector3
    angular_acceleration: Vector3


def zero_vector() -> Vector3:
    return Vector3(0.0, 0.0, 0.0)


def vector_add(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x + right.x, left.y + right.y, left.z + right.z)


def vector_subtract(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x - right.x, left.y - right.y, left.z - right.z)


def vector_scale(value: Vector3, scalar: float) -> Vector3:
    return Vector3(value.x * scalar, value.y * scalar, value.z * scalar)


def _clamp_scalar(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _clamp_vector_magnitude(value: Vector3, maximum: float) -> Vector3:
    magnitude = value.magnitude
    if magnitude <= maximum or magnitude == 0:
        return value
    return vector_scale(value, maximum / magnitude)


def quaternion_distance(left: Quaternion, right: Quaternion) -> float:
    dot = abs(
        left.x * right.x
        + left.y * right.y
        + left.z * right.z
        + left.w * right.w
    )
    return 2.0 * acos(max(-1.0, min(1.0, dot)))


def _quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    x = left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y
    y = left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x
    z = left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w
    w = left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z
    magnitude = sqrt(x * x + y * y + z * z + w * w)
    if magnitude == 0:
        raise BodySolverError(BodySolverFailureCode.NUMERICAL_FAILURE)
    return Quaternion(x / magnitude, y / magnitude, z / magnitude, w / magnitude)


def _desired_angular_velocity(
    current: Quaternion,
    target: Quaternion,
    dt: float,
    maximum: float,
) -> Vector3:
    conjugate = Quaternion(-current.x, -current.y, -current.z, current.w)
    delta = _quaternion_multiply(target, conjugate)
    if delta.w < 0:
        delta = Quaternion(-delta.x, -delta.y, -delta.z, -delta.w)
    angle = 2.0 * acos(max(-1.0, min(1.0, delta.w)))
    sine_half = sqrt(max(0.0, 1.0 - delta.w * delta.w))
    if angle == 0 or sine_half < 1e-12:
        return zero_vector()
    axis = Vector3(delta.x / sine_half, delta.y / sine_half, delta.z / sine_half)
    return vector_scale(axis, min(maximum, angle / dt))


def _integrate_orientation(
    current: Quaternion,
    angular_velocity: Vector3,
    dt: float,
) -> Quaternion:
    speed = angular_velocity.magnitude
    if speed == 0:
        return current
    half = speed * dt / 2.0
    scale = sin(half) / speed
    delta = Quaternion(
        angular_velocity.x * scale,
        angular_velocity.y * scale,
        angular_velocity.z * scale,
        cos(half),
    )
    return _quaternion_multiply(delta, current)


def _advance_vector_velocity(
    current_velocity: Vector3,
    current_acceleration: Vector3,
    desired_velocity: Vector3,
    *,
    max_velocity: float,
    max_acceleration: float,
    max_jerk: float,
    dt: float,
) -> tuple[Vector3, Vector3]:
    desired_velocity = _clamp_vector_magnitude(desired_velocity, max_velocity)
    desired_acceleration = _clamp_vector_magnitude(
        vector_scale(vector_subtract(desired_velocity, current_velocity), 1.0 / dt),
        max_acceleration,
    )
    acceleration_delta = _clamp_vector_magnitude(
        vector_subtract(desired_acceleration, current_acceleration),
        max_jerk * dt,
    )
    next_acceleration = _clamp_vector_magnitude(
        vector_add(current_acceleration, acceleration_delta),
        max_acceleration,
    )
    next_velocity = _clamp_vector_magnitude(
        vector_add(current_velocity, vector_scale(next_acceleration, dt)),
        max_velocity,
    )
    return next_velocity, next_acceleration


def _advance_coordinate(
    current: JointDofCoordinate,
    target_position: float,
    dynamic: JointDynamicLimit,
    hard_min: float,
    hard_max: float,
    dt: float,
) -> JointDofCoordinate:
    desired_velocity = _clamp_scalar(
        (target_position - current.position_radians) / dt,
        dynamic.max_velocity_radians_per_second,
    )
    desired_acceleration = _clamp_scalar(
        (desired_velocity - current.velocity_radians_per_second) / dt,
        dynamic.max_acceleration_radians_per_second2,
    )
    acceleration_delta = _clamp_scalar(
        desired_acceleration - current.acceleration_radians_per_second2,
        dynamic.max_jerk_radians_per_second3 * dt,
    )
    next_acceleration = _clamp_scalar(
        current.acceleration_radians_per_second2 + acceleration_delta,
        dynamic.max_acceleration_radians_per_second2,
    )
    next_velocity = _clamp_scalar(
        current.velocity_radians_per_second + next_acceleration * dt,
        dynamic.max_velocity_radians_per_second,
    )
    next_position = current.position_radians + next_velocity * dt
    bounded_position = max(hard_min, min(hard_max, next_position))
    if bounded_position != next_position:
        bounded_velocity = (bounded_position - current.position_radians) / dt
        bounded_acceleration = (
            bounded_velocity - current.velocity_radians_per_second
        ) / dt
        bounded_jerk = (
            bounded_acceleration - current.acceleration_radians_per_second2
        ) / dt
        if (
            abs(bounded_velocity) > dynamic.max_velocity_radians_per_second
            or abs(bounded_acceleration) > dynamic.max_acceleration_radians_per_second2
            or abs(bounded_jerk) > dynamic.max_jerk_radians_per_second3
        ):
            raise BodySolverError(BodySolverFailureCode.DYNAMIC_LIMIT_CONFLICT)
        next_velocity = bounded_velocity
        next_acceleration = bounded_acceleration
        next_position = bounded_position
    return JointDofCoordinate(
        current.axis,
        next_position,
        next_velocity,
        next_acceleration,
    )


def advance_joint_dofs(
    model: CanonicalBodyModel,
    current: BodyState,
    target_states: tuple[JointDofState, ...],
    dt: float,
) -> tuple[JointDofState, ...]:
    targets = {item.joint_id: item for item in target_states}
    definitions = {item.joint_id: item for item in model.joints}
    result: list[JointDofState] = []
    for state in current.joint_dof_states:
        target = targets.get(state.joint_id, state)
        target_by_axis = {item.axis: item for item in target.coordinates}
        definition = definitions[state.joint_id]
        hard_by_axis = {item.axis: item for item in definition.limits}
        dynamic_by_axis = {item.axis: item for item in definition.dynamic_limits}
        coordinates = tuple(
            _advance_coordinate(
                coordinate,
                target_by_axis[coordinate.axis].position_radians,
                dynamic_by_axis[coordinate.axis],
                hard_by_axis[coordinate.axis].hard_min_radians,
                hard_by_axis[coordinate.axis].hard_max_radians,
                dt,
            )
            for coordinate in state.coordinates
        )
        result.append(JointDofState(state.joint_id, coordinates))
    return tuple(result)


def body_velocity_from_dofs(
    model: CanonicalBodyModel,
    states: tuple[JointDofState, ...],
    root_velocity: JointVelocity,
    previous: BodyVelocity,
) -> BodyVelocity:
    state_by_joint = {item.joint_id: item for item in states}
    previous_by_joint = dict(previous.joint_local_velocities)
    values: list[tuple[str, JointVelocity]] = []
    for joint in model.joints:
        if joint.joint_id == model.root_joint_id:
            continue
        state = state_by_joint.get(joint.joint_id)
        if state is None:
            values.append(
                (
                    joint.joint_id,
                    previous_by_joint.get(
                        joint.joint_id,
                        JointVelocity(zero_vector(), zero_vector()),
                    ),
                )
            )
            continue
        by_axis = {item.axis: item.velocity_radians_per_second for item in state.coordinates}
        values.append(
            (
                joint.joint_id,
                JointVelocity(
                    zero_vector(),
                    Vector3(
                        by_axis.get(Axis.X, 0.0),
                        by_axis.get(Axis.Y, 0.0),
                        by_axis.get(Axis.Z, 0.0),
                    ),
                ),
            )
        )
    return BodyVelocity(root_velocity, tuple(values))


def advance_root(
    model: CanonicalBodyModel,
    current: BodyState,
    balance_mode: BodyBalanceMode,
    position_target: Vector3 | None,
    orientation_target: Quaternion | None,
    delta_velocity_target: Vector3 | None,
    phase_base_velocity: Vector3,
    dynamics_state: RootDynamicsState,
    dt: float,
) -> tuple[JointTransform, JointVelocity, RootDynamicsState]:
    limits = model.root_dynamic_limit
    if limits is None:
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
    current_velocity = current.velocity.root_world_velocity
    if position_target is not None:
        desired_linear = vector_scale(
            vector_subtract(position_target, current.pose.root_world_transform.position),
            1.0 / dt,
        )
    elif delta_velocity_target is not None:
        desired_linear = vector_add(phase_base_velocity, delta_velocity_target)
    elif balance_mode is BodyBalanceMode.TEMPORARY_FLIGHT_ALLOWED:
        desired_linear = current_velocity.linear
    else:
        desired_linear = zero_vector()
    next_linear, linear_acceleration = _advance_vector_velocity(
        current_velocity.linear,
        dynamics_state.linear_acceleration,
        desired_linear,
        max_velocity=limits.max_linear_velocity_mps,
        max_acceleration=limits.max_linear_acceleration_mps2,
        max_jerk=limits.max_linear_jerk_mps3,
        dt=dt,
    )
    desired_angular = (
        _desired_angular_velocity(
            current.pose.root_world_transform.rotation,
            orientation_target,
            dt,
            limits.max_angular_velocity_radps,
        )
        if orientation_target is not None
        else zero_vector()
    )
    next_angular, angular_acceleration = _advance_vector_velocity(
        current_velocity.angular,
        dynamics_state.angular_acceleration,
        desired_angular,
        max_velocity=limits.max_angular_velocity_radps,
        max_acceleration=limits.max_angular_acceleration_radps2,
        max_jerk=limits.max_angular_jerk_radps3,
        dt=dt,
    )
    next_position = vector_add(
        current.pose.root_world_transform.position,
        vector_scale(next_linear, dt),
    )
    next_rotation = _integrate_orientation(
        current.pose.root_world_transform.rotation,
        next_angular,
        dt,
    )
    return (
        JointTransform(next_position, next_rotation),
        JointVelocity(next_linear, next_angular),
        RootDynamicsState(linear_acceleration, angular_acceleration),
    )
