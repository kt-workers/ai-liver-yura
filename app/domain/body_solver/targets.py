from __future__ import annotations

from dataclasses import dataclass
from math import acos, cos, isclose, sin, sqrt

from app.domain.body import CanonicalBodyModel, Quaternion, Vector3
from app.domain.body_motion_planning import BodySpatialTargetKind

from .contracts import BodySolveTask, BodySolveTaskKind, BodySolverError, BodySolverFailureCode
from .physical import EndEffectorWorldFrame, end_effector_world_frame
from .spatial import BodySpatialTargetResolverPort, BodySpatialTargetSnapshot


@dataclass(frozen=True, slots=True)
class ResolvedBodyTaskTarget:
    goal_id: str
    position: Vector3 | None = None
    orientation: Quaternion | None = None
    root_delta_velocity: Vector3 | None = None
    target_ref: str | None = None
    target_generation: int | None = None


def _vector_add(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x + right.x, left.y + right.y, left.z + right.z)


def _vector_scale(value: Vector3, scalar: float) -> Vector3:
    return Vector3(value.x * scalar, value.y * scalar, value.z * scalar)


def _vector_dot(left: Vector3, right: Vector3) -> float:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _vector_cross(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(
        left.y * right.z - left.z * right.y,
        left.z * right.x - left.x * right.z,
        left.x * right.y - left.y * right.x,
    )


def _normalize(value: Vector3) -> Vector3:
    magnitude = value.magnitude
    if magnitude == 0:
        raise BodySolverError(BodySolverFailureCode.INFEASIBLE_TARGET)
    return Vector3(value.x / magnitude, value.y / magnitude, value.z / magnitude)


def _quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    x = left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y
    y = left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x
    z = left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w
    w = left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z
    magnitude = sqrt(x * x + y * y + z * z + w * w)
    if magnitude == 0:
        raise BodySolverError(BodySolverFailureCode.NUMERICAL_FAILURE)
    return Quaternion(x / magnitude, y / magnitude, z / magnitude, w / magnitude)


def _slerp(left: Quaternion, right: Quaternion, fraction: float) -> Quaternion:
    if fraction <= 0:
        return left
    if fraction >= 1:
        return right
    dot = left.x * right.x + left.y * right.y + left.z * right.z + left.w * right.w
    rx, ry, rz, rw = right.x, right.y, right.z, right.w
    if dot < 0:
        dot = -dot
        rx, ry, rz, rw = -rx, -ry, -rz, -rw
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        x = left.x + fraction * (rx - left.x)
        y = left.y + fraction * (ry - left.y)
        z = left.z + fraction * (rz - left.z)
        w = left.w + fraction * (rw - left.w)
        magnitude = sqrt(x * x + y * y + z * z + w * w)
        if magnitude == 0:
            raise BodySolverError(BodySolverFailureCode.NUMERICAL_FAILURE)
        return Quaternion(x / magnitude, y / magnitude, z / magnitude, w / magnitude)
    theta = acos(dot)
    denominator = sin(theta)
    left_weight = sin((1.0 - fraction) * theta) / denominator
    right_weight = sin(fraction * theta) / denominator
    return Quaternion(
        left.x * left_weight + rx * right_weight,
        left.y * left_weight + ry * right_weight,
        left.z * left_weight + rz * right_weight,
        left.w * left_weight + rw * right_weight,
    )


def _frame_orientation(frame: EndEffectorWorldFrame) -> Quaternion:
    forward = _normalize(frame.forward_axis)
    up = _normalize(frame.up_axis)
    right = _normalize(_vector_cross(up, forward))
    up = _normalize(_vector_cross(forward, right))
    m00, m01, m02 = right.x, up.x, forward.x
    m10, m11, m12 = right.y, up.y, forward.y
    m20, m21, m22 = right.z, up.z, forward.z
    trace = m00 + m11 + m22
    if trace > 0:
        scale = sqrt(trace + 1.0) * 2.0
        return Quaternion((m21 - m12) / scale, (m02 - m20) / scale, (m10 - m01) / scale, scale / 4.0)
    if m00 > m11 and m00 > m22:
        scale = sqrt(1.0 + m00 - m11 - m22) * 2.0
        return Quaternion(scale / 4.0, (m01 + m10) / scale, (m02 + m20) / scale, (m21 - m12) / scale)
    if m11 > m22:
        scale = sqrt(1.0 + m11 - m00 - m22) * 2.0
        return Quaternion((m01 + m10) / scale, scale / 4.0, (m12 + m21) / scale, (m02 - m20) / scale)
    scale = sqrt(1.0 + m22 - m00 - m11) * 2.0
    return Quaternion((m02 + m20) / scale, (m12 + m21) / scale, scale / 4.0, (m10 - m01) / scale)


def _rotation_between(source: Vector3, target: Vector3) -> Quaternion:
    start = _normalize(source)
    end = _normalize(target)
    dot = min(1.0, max(-1.0, _vector_dot(start, end)))
    if dot > 1.0 - 1e-12:
        return Quaternion(0, 0, 0, 1)
    if dot < -1.0 + 1e-12:
        basis = Vector3(1, 0, 0) if abs(start.x) < 0.9 else Vector3(0, 1, 0)
        axis = _normalize(_vector_cross(start, basis))
        return Quaternion(axis.x, axis.y, axis.z, 0)
    axis = _vector_cross(start, end)
    scale = sqrt((1.0 + dot) * 2.0)
    inverse = 1.0 / scale
    return Quaternion(axis.x * inverse, axis.y * inverse, axis.z * inverse, scale / 2.0)


def _task_end_effector_id(task: BodySolveTask, model: CanonicalBodyModel) -> str:
    if len(task.chain_ids) == 1:
        chain_id = task.chain_ids[0]
        chain = next((item for item in model.kinematic_chains if item.chain_id == chain_id), None)
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


def _chain_reach_budget_m(task: BodySolveTask, model: CanonicalBodyModel) -> float:
    if len(task.chain_ids) != 1:
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
    chain = next(
        (item for item in model.kinematic_chains if item.chain_id == task.chain_ids[0]),
        None,
    )
    if chain is None:
        raise BodySolverError(BodySolverFailureCode.UNKNOWN_BODY_REFERENCE)
    pairs = set(zip(chain.joint_ids, chain.joint_ids[1:], strict=False))
    normalized = sum(
        segment.normalized_length
        for segment in model.segments
        if (segment.proximal_joint_id, segment.distal_joint_id) in pairs
    )
    if normalized <= 0:
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
    return normalized * model.reference_height


def _target_snapshot(
    target_ref: str,
    resolver: BodySpatialTargetResolverPort,
) -> BodySpatialTargetSnapshot:
    snapshot = resolver.resolve(target_ref)
    if snapshot is None or snapshot.target_ref != target_ref:
        raise BodySolverError(BodySolverFailureCode.TARGET_GEOMETRY_UNAVAILABLE)
    return snapshot


def resolve_body_task_target(
    task: BodySolveTask,
    model: CanonicalBodyModel,
    pose: object,
    resolver: BodySpatialTargetResolverPort,
) -> ResolvedBodyTaskTarget:
    from app.domain.body import BodyPose

    if not isinstance(pose, BodyPose):
        raise BodySolverError(BodySolverFailureCode.INVALID_DOF_STATE)
    spatial = task.spatial_target
    if spatial is None:
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)

    if task.kind is BodySolveTaskKind.ROOT_IMPULSE_TARGET:
        if spatial.kind is not BodySpatialTargetKind.DIRECTION or spatial.direction is None:
            raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
        limit = model.root_dynamic_limit
        if limit is None:
            raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
        return ResolvedBodyTaskTarget(
            task.goal_id,
            root_delta_velocity=_vector_scale(
                spatial.direction,
                spatial.extent * limit.impulse_budget_mps,
            ),
        )

    end_effector_id = _task_end_effector_id(task, model)
    current = end_effector_world_frame(model, pose, end_effector_id)
    if spatial.kind is BodySpatialTargetKind.TARGET_REF:
        if spatial.target_ref is None:
            raise BodySolverError(BodySolverFailureCode.TARGET_GEOMETRY_UNAVAILABLE)
        snapshot = _target_snapshot(spatial.target_ref, resolver)
        if task.kind in {BodySolveTaskKind.POSITION_TARGET, BodySolveTaskKind.CONTACT_TARGET}:
            if snapshot.position is None:
                raise BodySolverError(BodySolverFailureCode.TARGET_GEOMETRY_UNAVAILABLE)
            if task.kind is BodySolveTaskKind.CONTACT_TARGET and not isclose(
                spatial.extent, 1.0, rel_tol=0.0, abs_tol=0.0
            ):
                raise BodySolverError(BodySolverFailureCode.CONTACT_INFEASIBLE)
            delta = Vector3(
                snapshot.position.x - current.position.x,
                snapshot.position.y - current.position.y,
                snapshot.position.z - current.position.z,
            )
            return ResolvedBodyTaskTarget(
                task.goal_id,
                position=_vector_add(current.position, _vector_scale(delta, spatial.extent)),
                target_ref=snapshot.target_ref,
                target_generation=snapshot.generation,
            )
        if task.kind is BodySolveTaskKind.ORIENTATION_TARGET:
            if snapshot.orientation is None:
                raise BodySolverError(BodySolverFailureCode.TARGET_GEOMETRY_UNAVAILABLE)
            current_orientation = _frame_orientation(current)
            return ResolvedBodyTaskTarget(
                task.goal_id,
                orientation=_slerp(current_orientation, snapshot.orientation, spatial.extent),
                target_ref=snapshot.target_ref,
                target_generation=snapshot.generation,
            )
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)

    if spatial.direction is None:
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
    if task.kind is BodySolveTaskKind.POSITION_TARGET:
        if task.chain_ids:
            distance = spatial.extent * _chain_reach_budget_m(task, model)
            return ResolvedBodyTaskTarget(
                task.goal_id,
                position=_vector_add(current.position, _vector_scale(spatial.direction, distance)),
            )
        raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)
    if task.kind is BodySolveTaskKind.ORIENTATION_TARGET:
        current_orientation = _frame_orientation(current)
        full_alignment = _quaternion_multiply(
            _rotation_between(current.forward_axis, spatial.direction),
            current_orientation,
        )
        return ResolvedBodyTaskTarget(
            task.goal_id,
            orientation=_slerp(current_orientation, full_alignment, spatial.extent),
        )
    raise BodySolverError(BodySolverFailureCode.UNSUPPORTED_CAPABILITY)


def validate_tracking_update(
    previous: BodySpatialTargetSnapshot,
    current: BodySpatialTargetSnapshot,
) -> None:
    if previous.target_ref != current.target_ref:
        raise BodySolverError(BodySolverFailureCode.TARGET_GEOMETRY_UNAVAILABLE)
    if previous.generation != current.generation:
        raise BodySolverError(BodySolverFailureCode.TARGET_GENERATION_CHANGED)
