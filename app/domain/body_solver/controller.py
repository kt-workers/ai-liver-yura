from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from app.domain.body import (
    BodyPose,
    BodyState,
    BodyVelocity,
    CanonicalBodyModel,
    Quaternion,
    Vector3,
    project_body_pose_from_dof,
)
from app.domain.body_realtime.contracts import RealtimeOverlayBundle
from app.domain.contracts.common import require_aware, require_identifier

from .contracts import (
    BodyMotionExecutionReport,
    BodyMotionExecutionStatus,
    BodyMotionResidual,
    BodyPoseFrame,
    BodySolverError,
    BodySolverFailureCode,
    BodySolveTask,
    BodySolveTaskKind,
    BodyTrajectoryPhase,
    ExecutableBodyTrajectory,
)
from .dynamics import (
    RootDynamicsState,
    advance_joint_dofs,
    advance_root,
    body_velocity_from_dofs,
    quaternion_distance,
    vector_add,
    vector_subtract,
    zero_vector,
)
from .execution import BodyMotionExecutionTracker
from .overlay import select_overlay_channels
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
        if (
            type(started_monotonic_s) not in (int, float)
            or not isfinite(started_monotonic_s)
        ):
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
        self._phase_targets: tuple[ResolvedBodyTaskTarget, ...] | None = None
        self._phase_root_base_velocity = authority.current.velocity.root_world_velocity.linear
        self._root_dynamics = RootDynamicsState(zero_vector(), zero_vector())
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

    def _targets_for_phase(
        self,
        phase: BodyTrajectoryPhase,
        current: BodyState,
    ) -> tuple[ResolvedBodyTaskTarget, ...]:
        if phase.phase_id != self._phase_id:
            self._phase_id = phase.phase_id
            self._phase_root_base_velocity = current.velocity.root_world_velocity.linear
            self._phase_targets = tuple(
                resolve_body_task_target(
                    task,
                    self._model,
                    current.pose,
                    self._target_resolver,
                )
                for task in phase.tasks
            )
        if self._phase_targets is None:
            raise BodySolverError(BodySolverFailureCode.INVALID_PLAN)
        return self._phase_targets

    def _partition_tasks(
        self,
        phase: BodyTrajectoryPhase,
        targets: tuple[ResolvedBodyTaskTarget, ...],
    ) -> tuple[
        tuple[BodySolveTask, ...],
        tuple[ResolvedBodyTaskTarget, ...],
        set[str],
    ]:
        root_task_ids = {
            task.goal_id
            for task in phase.tasks
            if task.kind is BodySolveTaskKind.ROOT_IMPULSE_TARGET
            or (
                not task.chain_ids
                and set(task.joint_ids) == {self._model.root_joint_id}
            )
        }
        return (
            tuple(task for task in phase.tasks if task.goal_id not in root_task_ids),
            tuple(target for target in targets if target.goal_id not in root_task_ids),
            root_task_ids,
        )

    def _solve_joint_targets(
        self,
        current: BodyState,
        joint_tasks: tuple[BodySolveTask, ...],
        joint_targets: tuple[ResolvedBodyTaskTarget, ...],
    ) -> BodyIKSolution | None:
        if not joint_tasks:
            return None
        solution = solve_body_tasks(
            self._model,
            current,
            joint_tasks,
            joint_targets,
            self._policy,
        )
        if solution.feasibility is not BodySolveFeasibility.FEASIBLE:
            raise BodySolverError(BodySolverFailureCode.INFEASIBLE_TARGET)
        return solution

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
            is_root = (
                not task.chain_ids
                and set(task.joint_ids) == {self._model.root_joint_id}
            )
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
            is_root = (
                not task.chain_ids
                and set(task.joint_ids) == {self._model.root_joint_id}
            )
            if not is_root and task.kind is not BodySolveTaskKind.ROOT_IMPULSE_TARGET:
                continue
            target = target_by_goal[task.goal_id]
            position_error: float | None = None
            orientation_error: float | None = None
            velocity_error: float | None = None
            if target.position is not None:
                position_error = vector_subtract(
                    target.position,
                    pose.root_world_transform.position,
                ).magnitude
            if target.orientation is not None:
                orientation_error = quaternion_distance(
                    pose.root_world_transform.rotation,
                    target.orientation,
                )
            if target.root_delta_velocity is not None:
                desired = vector_add(
                    self._phase_root_base_velocity,
                    target.root_delta_velocity,
                )
                velocity_error = vector_subtract(
                    desired,
                    velocity.root_world_velocity.linear,
                ).magnitude
            result.append(
                BodyTaskResidual(
                    task.goal_id,
                    position_error,
                    orientation_error,
                    velocity_error,
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
            velocity_ok = (
                item.linear_velocity_error_mps is None
                or item.linear_velocity_error_mps <= self._policy.numeric_epsilon
            )
            if position_ok and orientation_ok and velocity_ok:
                achieved.append(item.goal_id)
            else:
                all_complete = False
            scalar = max(
                item.position_error_m or 0.0,
                item.orientation_error_radians or 0.0,
                item.linear_velocity_error_mps or 0.0,
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
        if self._tracker.current.status is BodyMotionExecutionStatus.COMPLETED:
            raise BodySolverError(BodySolverFailureCode.INVALID_PLAN)

        current = self._authority.current
        current.validate_physical_for(self._model)
        dt = self._tick_dt(monotonic_now_s)
        elapsed = float(monotonic_now_s) - self._started_monotonic_s
        phase = self._phase_for(elapsed)
        targets = self._targets_for_phase(phase, current)
        joint_tasks, joint_targets, _ = self._partition_tasks(phase, targets)
        solution = self._solve_joint_targets(current, joint_tasks, joint_targets)
        target_dofs = (
            solution.joint_dof_states
            if solution is not None
            else current.joint_dof_states
        )
        next_dofs = advance_joint_dofs(self._model, current, target_dofs, dt)
        root_position, root_orientation, root_delta = self._root_targets(
            phase.tasks,
            targets,
        )
        root_transform, root_velocity, self._root_dynamics = advance_root(
            self._model,
            current,
            phase.balance_mode,
            root_position,
            root_orientation,
            root_delta,
            self._phase_root_base_velocity,
            self._root_dynamics,
            dt,
        )
        next_pose = project_body_pose_from_dof(
            self._model,
            root_transform,
            next_dofs,
        )
        next_velocity = body_velocity_from_dofs(
            self._model,
            next_dofs,
            root_velocity,
            current.velocity,
        )
        channel_values, applied, degraded = select_overlay_channels(
            overlay_bundle,
            current.revision,
        )

        # 現行#340はchannel-only overlayでありCanonical joint poseを変更しない。
        # それでもfinal composition後のhard/balance gateとしてここで再検証する。
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
        actual_residuals = joint_actual + self._root_residuals(
            frame.pose,
            frame.velocity,
            phase.tasks,
            targets,
        )
        complete, achieved, report_residuals = self._completion(actual_residuals)
        report = self._tracker.current
        if report.status is BodyMotionExecutionStatus.PLANNED:
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
