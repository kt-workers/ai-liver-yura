from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import acos, cos, isfinite, sin, sqrt

from app.domain.body import (
    Axis,
    BodyPose,
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
    project_body_pose_from_dof,
)
from app.domain.body_motion_planning import BodyBalanceMode
from app.domain.body_realtime.contracts import RealtimeOverlayBundle
from app.domain.contracts.common import require_aware, require_identifier

from .contracts import (
    BodyFrameChannelValue,
    BodyMotionExecutionReport,
    BodyMotionResidual,
    BodyPoseFrame,
    BodySolveTask,
    BodySolveTaskKind,
    BodySolverError,
    BodySolverFailureCode,
    BodyTrajectoryPhase,
    ExecutableBodyTrajectory,
)
from .execution import BodyMotionExecutionTracker
from .physical import BodyBalanceEvidence, validate_balance
from .policy import BodySolverPolicy
from .solver import (
    BodyIKSolution,
    BodySolveFeasibility,
    BodyTaskResidual,
    evaluate_body_task_residuals,
    solve_body_tasks,
)
from .spatial import BodySpatialTargetResolverPort
from .state_authority import BodyStateAuthority
from .targets import ResolvedBodyTaskTarget, resolve_body_task_target


@dataclass(frozen=True, slots=True)
class BodyControllerTickResult:
    frame: BodyPoseFrame
    balance: BodyBalanceEvidence
    execution_report: BodyMotionExecutionReport
    phase_id: str
    ik_iterations: int
    actual_residuals: tuple[BodyTaskResidual, ...]


def _vector_add(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x + right.x, left.y + right.y, left.z + right.z)


def _vector_subtract(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x - right.x, left.y - right.y, left.z - right.z)


def _vector_scale(value: Vector3, scalar: float) -> Vector3:
    return Vector3(value.x * scalar, value.y * scalar, value.z * scalar)


def _clamp_scalar(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _clamp_vector_magnitude(value: Vector3, maximum: float) -> Vector3:
    magnitude = value.magnitude
    if magnitude <= maximum or magnitude == 0:
        return value
    return _vector_scale(value, maximum / magnitude)


def _zero_vector() -> Vector3:
    return Vector3(0, 0, 0)


def _quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    x = left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y
    y = left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x
    z = left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w
    w = left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z
    magnitude = sqrt(x * x + y * y + z * z + w * w)
    if magnitude == 0:
        raise BodySolverError(BodySolverFailureCode.NUMERICAL_FAILURE)
    return Quaternion(x / magnitude, y / magnitude, z / magnitude, w / magnitude)


def _quaternion_distance(left: Quaternion, right: Quaternion) -> float:
    dot = abs(
        left.x * right.x
        + left.y * right.y
        + left.z * right.z
        + left.w * right.w
    )
    return 2.0 * acos(max(-1.0, min(1.0, dot)))


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
        return _zero_vector()
    axis = Vector3(delta.x / sine_half, delta.y / sine_half, delta.z / sine_half)
    return _vector_scale(axis, min(maximum, angle / dt))


def _integrate_orientation(current: Quaternion, angular_velocity: Vector3, dt: float) -> Quaternion:
    speed = angular_velocity.magnitude
    if speed == 0:
        return current
    angle = speed * dt
    half = angle / 2.0
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
        _vector_scale(_vector_subtract(desired_velocity, current_velocity), 1.0 / dt),
        max_acceleration,
    )
    acceleration_delta = _clamp_vector_magnitude(
        _vector_subtract(desired_acceleration, current_acceleration),
        max_jerk * dt,
    )
    next_acceleration = _clamp_vector_magnitude(
        _vector_add(current_acceleration, acceleration_delta),
        max_acceleration,
    )
    next_velocity = _clamp_vector_magnitude(
        _vector_add(current_velocity, _vector_scale(next_acceleration, dt)),
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


def _body_velocity_from_dofs(
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
                        JointVelocity(_zero_vector(), _zero_vector()),
                    ),
                )
            )
            continue
        by_axis = {item.axis: item.velocity_radians_per_second for item in state.coordinates}
        angular = Vector3(
            by_axis.get(Axis.X, 0.0),
            by_axis.get(Axis.Y, 0.0),
            by_axis.get(Axis.Z, 0.0),
        )
        values.append((joint.joint_id, JointVelocity(_zero_vector(), angular)))
    return BodyVelocity(root_velocity, tuple(values))


def _select_overlay_channels(
    bundle: RealtimeOverlayBundle | None,
    current_revision: int,
) -> tuple[
    tuple[BodyFrameChannelValue, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    if bundle is None:
        return (), (), ()
    overlays = tuple(bundle.channel_overlays)
    if bundle.based_on_body_state_revision != current_revision:
        return (), (), tuple(sorted(item.overlay_id for item in overlays))
    by_channel: dict[object, list[object]] = {}
    for overlay in overlays:
        by_channel.setdefault(overlay.channel, []).append(overlay)
    values: list[BodyFrameChannelValue] = []
    applied: list[str] = []
    degraded: list[str] = []
    for channel in sorted(by_channel, key=lambda item: item.value):
        candidates = sorted(
            by_channel[channel],
            key=lambda item: (-item.priority, item.overlay_id),
        )
        winner = candidates[0]
        if winner.strength > 0:
            values.append(BodyFrameChannelValue(winner.channel, winner.value))
            applied.append(winner.overlay_id)
        else:
            degraded.append(winner.overlay_id)
        degraded.extend(item.overlay_id for item in candidates[1:])
    return tuple(values), tuple(sorted(applied)), tuple(sorted(degraded))


class BodyContinuousController:
    """#339のsingle-writer physical control tick。外部I/Oをawaitしない。"""

    def __init__(
        self,
        model: CanonicalBodyModel,
        policy: BodySolverPolicy,
        trajectory: ExecutableBodyTrajectory,
        authority: BodyStateAuthority,
        target_resolver: BodySpatialTargetResolverPort,
        *,
        started_monotonic_s: float,
    ) -> None:
        if not isinstance(model, CanonicalBodyModel):
            raise ValueError("model が不正です")
        if not isinstance(policy, BodySolverPolicy):
            raise ValueError("policy が不正です")
        if not isinstance(trajectory, ExecutableBodyTrajectory):
            raise ValueError("trajectory が不正です")
        if not isinstance(authority, BodyStateAuthority):
            raise ValueError("authority が不正です")
        if type(started_monotonic_s) not in (int, float) or not isfinite(started_monotonic_s):
            raise ValueError("started_monotonic_s が不正です")
        model.require_physical_control_contract()
        self._validate_trajectory_generation(model, policy, trajectory)
        authority.current.validate_physical_for(model)
        self._model = model
        self._policy = policy
        self._trajectory = trajectory
        self._authority = authority
        self._target_resolver = target_resolver
        self._started_monotonic_s = float(started_monotonic_s)
        self._last_monotonic_s: float | None = None
        self._phase_id: str | None = None
        self._phase_root_base_velocity = authority.current.velocity.root_world_velocity.linear
        self._root_linear_acceleration = _zero_vector()
        self._root_angular_acceleration = _zero_vector()
        self._tracker = BodyMotionExecutionTracker(
            trajectory.plan_id,
            trajectory.trajectory_id,
        )

    @staticmethod
    def _validate_trajectory_generation(
        model: CanonicalBodyModel,
        policy: BodySolverPolicy,
        trajectory: ExecutableBodyTrajectory,
    ) -> None:
        if trajectory.body_model_id != model.body_model_id:
            raise BodySolverError(BodySolverFailureCode.MODEL_MISMATCH)
        if trajectory.body_model_revision != model.body_model_revision:
            raise BodySolverError(BodySolverFailureCode.MODEL_REVISION_MISMATCH)
        if trajectory.body_model_fingerprint != model.body_model_fingerprint:
            raise BodySolverError(BodySolverFailureCode.MODEL_FINGERPRINT_MISMATCH)
        if trajectory.solver_policy_revision != policy.policy_revision:
            raise BodySolverError(BodySolverFailureCode.INVALID_SOLVER_POLICY)

    @property
    def execution_report(self) -> BodyMotionExecutionReport:
        return self._tracker.current

    def _phase_for(self, elapsed: float) -> BodyTrajectoryPhase:
        for phase in self._trajectory.phases:
            if elapsed < phase.end_offset_s:
                return phase
        return self._trajectory.phases[-1]

    def _tick_dt(self, monotonic_now_s: float) -> float:
        if type(monotonic_now_s) not in (int, float) or not isfinite(monotonic_now_s):
            raise ValueError("monotonic_now_s が不正です")
        value = float(monotonic_now_s)
        if value < self._started_monotonic_s:
            raise BodySolverError(BodySolverFailureCode.STALE_HARD_DEPENDENCY)
        previous = self._last_monotonic_s
        self._last_monotonic_s = value
        if previous is None:
            return self._policy.target_control_interval_seconds
        dt = value - previous
        if dt <= 0:
            raise BodySolverError(BodySolverFailureCode.DYNAMIC_LIMIT_CONFLICT)
        return dt

    def _advance_dofs(
        self,
        current: BodyState,
        solution: BodyIKSolution | None,
        dt: float,
    ) -> tuple[JointDofState, ...]:
        target_states = (
            {item.joint_id: item for item in solution.joint_dof_states}
            if solution is not None
            else {item.joint_id: item for item in current.joint_dof_states}
        )
        definitions = {item.joint_id: item for item in self._model.joints}
        result: list[JointDofState] = []
        for state in current.joint_dof_states:
            target = target_states[state.joint_id]
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

    def _root_targets(
        self,
        tasks: tuple[BodySolveTask, ...],
        targets: tuple[ResolvedBodyTaskTarget, ...],
    ) -> tuple[Vector3 | None, Quaternion | None, Vector3 | None]:
        target_by_goal = {item.goal_id: item for item in targets}
        position: Vector3 | None = None
        orientation: Quaternion | None = None
        delta_velocity: Vector3 | None = None
        for task in tasks:
            is_root = not task.chain_ids and set(task.joint_ids) == {self._model.root_joint_id}
            if not is_root and task.kind is not BodySolveTaskKind.ROOT_IMPULSE_TARGET:
                continue
            target = target_by_goal[task.goal_id]
            if target.position is not None:
                if position is not None:
                    raise BodySolverError(BodySolverFailureCode.HARD_LIMIT_CONFLICT)
                position = target.position
            if target.orientation is not None:
                if orientation is not None:
                    raise BodySolverError(BodySolverFailureCode.HARD_LIMIT_CONFLICT)
                orientation = target.orientation
            if target.root_delta_velocity is not None:
                if delta_velocity is not None:
                    raise BodySolverError(BodySolverFailureCode.HARD_LIMIT_CONFLICT)
                delta_velocity = target.root_delta_velocity
        if position is not None and delta_velocity is not None:
            raise BodySolverError(BodySolverFailureCode.HARD_LIMIT_CONFLICT)
        return position, orientation, delta_velocity

    def _advance_root(
        self,
        current: BodyState,
        phase: BodyTrajectoryPhase,
        root_position_target: Vector3 | None,
        root_orientation_target: Quaternion | None,
        root_delta_velocity: Vector3 | None,
        dt: float,
    ) -> tuple[JointTransform, JointVelocity]:
        limits = self._model.root_dynamic_limit
        if limits is None:
            raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
        current_root_velocity = current.velocity.root_world_velocity
        if root_position_target is not None:
            desired_linear = _vector_scale(
                _vector_subtract(root_position_target, current.pose.root_world_transform.position),
                1.0 / dt,
            )
        elif root_delta_velocity is not None:
            desired_linear = _vector_add(
                self._phase_root_base_velocity,
                root_delta_velocity,
            )
        elif phase.balance_mode is BodyBalanceMode.TEMPORARY_FLIGHT_ALLOWED:
            desired_linear = current_root_velocity.linear
        else:
            desired_linear = _zero_vector()
        next_linear, self._root_linear_acceleration = _advance_vector_velocity(
            current_root_velocity.linear,
            self._root_linear_acceleration,
            desired_linear,
            max_velocity=limits.max_linear_velocity_mps,
            max_acceleration=limits.max_linear_acceleration_mps2,
            max_jerk=limits.max_linear_jerk_mps3,
            dt=dt,
        )
        if root_orientation_target is not None:
            desired_angular = _desired_angular_velocity(
                current.pose.root_world_transform.rotation,
                root_orientation_target,
                dt,
                limits.max_angular_velocity_radps,
            )
        else:
            desired_angular = _zero_vector()
        next_angular, self._root_angular_acceleration = _advance_vector_velocity(
            current_root_velocity.angular,
            self._root_angular_acceleration,
            desired_angular,
            max_velocity=limits.max_angular_velocity_radps,
            max_acceleration=limits.max_angular_acceleration_radps2,
            max_jerk=limits.max_angular_jerk_radps3,
            dt=dt,
        )
        next_position = _vector_add(
            current.pose.root_world_transform.position,
            _vector_scale(next_linear, dt),
        )
        next_rotation = _integrate_orientation(
            current.pose.root_world_transform.rotation,
            next_angular,
            dt,
        )
        return JointTransform(next_position, next_rotation), JointVelocity(
            next_linear,
            next_angular,
        )

    def _root_residuals(
        self,
        pose: BodyPose,
        velocity: BodyVelocity,
        tasks: tuple[BodySolveTask, ...],
        targets: tuple[ResolvedBodyTaskTarget, ...],
    ) -> tuple[BodyTaskResidual, ...]:
        target_by_goal = {item.goal_id: item for item in targets}
        result: list[BodyTaskResidual] = []
        for task in tasks:
            is_root = not task.chain_ids and set(task.joint_ids) == {self._model.root_joint_id}
            if not is_root and task.kind is not BodySolveTaskKind.ROOT_IMPULSE_TARGET:
                continue
            target = target_by_goal[task.goal_id]
            position_error: float | None = None
            orientation_error: float | None = None
            if target.position is not None:
                position_error = _vector_subtract(
                    target.position,
                    pose.root_world_transform.position,
                ).magnitude
            if target.orientation is not None:
                orientation_error = _quaternion_distance(
                    pose.root_world_transform.rotation,
                    target.orientation,
                )
            if target.root_delta_velocity is not None:
                desired = _vector_add(
                    self._phase_root_base_velocity,
                    target.root_delta_velocity,
                )
                position_error = _vector_subtract(
                    desired,
                    velocity.root_world_velocity.linear,
                ).magnitude
            result.append(
                BodyTaskResidual(
                    task.goal_id,
                    position_error,
                    orientation_error,
                )
            )
        return tuple(result)

    def _completion(
        self,
        residuals: tuple[BodyTaskResidual, ...],
    ) -> tuple[bool, tuple[str, ...], tuple[BodyMotionResidual, ...]]:
        position_tolerance = self._policy.position_tolerance_m(
            self._model.reference_height,
            completion=True,
        )
        achieved: list[str] = []
        reports: list[BodyMotionResidual] = []
        all_complete = True
        for item in residuals:
            position_ok = (
                item.position_error_m is None
                or item.position_error_m <= position_tolerance
            )
            orientation_ok = (
                item.orientation_error_radians is None
                or item.orientation_error_radians
                <= self._policy.completion_orientation_tolerance_radians
            )
            if position_ok and orientation_ok:
                achieved.append(item.goal_id)
            else:
                all_complete = False
            scalar = max(
                item.position_error_m or 0.0,
                item.orientation_error_radians or 0.0,
            )
            reports.append(BodyMotionResidual(item.goal_id, scalar))
        return all_complete, tuple(achieved), tuple(reports)

    def tick(
        self,
        *,
        observed_at: datetime,
        monotonic_now_s: float,
        active_support_contact_ids: tuple[str, ...],
        overlay_bundle: RealtimeOverlayBundle | None,
        frame_id: str,
        trace_id: str,
    ) -> BodyControllerTickResult:
        require_aware(observed_at, "observed_at")
        require_identifier(frame_id, "frame_id")
        require_identifier(trace_id, "trace_id")
        current = self._authority.current
        current.validate_physical_for(self._model)
        dt = self._tick_dt(monotonic_now_s)
        elapsed = float(monotonic_now_s) - self._started_monotonic_s
        phase = self._phase_for(elapsed)
        if phase.phase_id != self._phase_id:
            self._phase_id = phase.phase_id
            self._phase_root_base_velocity = current.velocity.root_world_velocity.linear

        targets = tuple(
            resolve_body_task_target(
                task,
                self._model,
                current.pose,
                self._target_resolver,
            )
            for task in phase.tasks
        )
        root_task_ids = {
            task.goal_id
            for task in phase.tasks
            if task.kind is BodySolveTaskKind.ROOT_IMPULSE_TARGET
            or (not task.chain_ids and set(task.joint_ids) == {self._model.root_joint_id})
        }
        joint_tasks = tuple(
            task for task in phase.tasks if task.goal_id not in root_task_ids
        )
        joint_targets = tuple(
            target for target in targets if target.goal_id not in root_task_ids
        )
        solution: BodyIKSolution | None = None
        if joint_tasks:
            solution = solve_body_tasks(
                self._model,
                current,
                joint_tasks,
                joint_targets,
                self._policy,
            )
            if solution.feasibility is not BodySolveFeasibility.FEASIBLE:
                raise BodySolverError(BodySolverFailureCode.INFEASIBLE_TARGET)
        next_dofs = self._advance_dofs(current, solution, dt)
        root_position, root_orientation, root_delta = self._root_targets(
            phase.tasks,
            targets,
        )
        root_transform, root_velocity = self._advance_root(
            current,
            phase,
            root_position,
            root_orientation,
            root_delta,
            dt,
        )
        next_pose = project_body_pose_from_dof(
            self._model,
            root_transform,
            next_dofs,
        )
        next_velocity = _body_velocity_from_dofs(
            self._model,
            next_dofs,
            root_velocity,
            current.velocity,
        )
        channel_values, applied, degraded = _select_overlay_channels(
            overlay_bundle,
            current.revision,
        )
        balance = validate_balance(
            self._model,
            next_pose,
            phase.balance_mode,
            active_support_contact_ids,
            self._policy,
        )
        frame = self._authority.commit_validated_frame(
            expected_revision=current.revision,
            frame_id=frame_id,
            observed_at=observed_at,
            pose=next_pose,
            velocity=next_velocity,
            active_plan_id=self._trajectory.plan_id,
            active_trajectory_id=self._trajectory.trajectory_id,
            channel_values=channel_values,
            applied_overlay_refs=applied,
            degraded_overlay_refs=degraded,
            trace_id=trace_id,
            joint_dof_states=next_dofs,
        )

        joint_actual = (
            evaluate_body_task_residuals(
                self._model,
                frame.pose,
                joint_tasks,
                joint_targets,
            )
            if joint_tasks
            else ()
        )
        root_actual = self._root_residuals(
            frame.pose,
            frame.velocity,
            phase.tasks,
            targets,
        )
        actual_residuals = joint_actual + root_actual
        complete, achieved, report_residuals = self._completion(actual_residuals)
        report = self._tracker.current
        if report.status.value == "planned":
            report = self._tracker.start(observed_at)
        final_time_reached = elapsed >= self._trajectory.phases[-1].end_offset_s
        if complete and final_time_reached:
            report = self._tracker.complete(
                observed_at,
                achieved_target_refs=achieved,
                residuals=report_residuals,
            )
        else:
            report = self._tracker.observe(
                observed_at,
                achieved_target_refs=achieved,
                residuals=report_residuals,
            )
        return BodyControllerTickResult(
            frame,
            balance,
            report,
            phase.phase_id,
            0 if solution is None else solution.iterations,
            actual_residuals,
        )
