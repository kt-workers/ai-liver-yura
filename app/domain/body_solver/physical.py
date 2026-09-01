from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from app.domain.body import BodyPose, CanonicalBodyModel, JointTransform, Quaternion, Vector3
from app.domain.body_motion_planning import BodyBalanceMode

from .contracts import BodySolverError, BodySolverFailureCode
from .kinematics import forward_kinematics
from .policy import BodySolverPolicy


@dataclass(frozen=True, slots=True)
class EndEffectorWorldFrame:
    end_effector_id: str
    position: Vector3
    forward_axis: Vector3
    up_axis: Vector3


@dataclass(frozen=True, slots=True)
class BodyBalanceEvidence:
    center_of_mass_world: Vector3
    active_support_contact_ids: tuple[str, ...]
    support_polygon_xz: tuple[tuple[float, float], ...]
    support_margin_m: float | None
    grounded_requirement_applied: bool


def _rotate(rotation: Quaternion, value: Vector3) -> Vector3:
    ux, uy, uz = rotation.x, rotation.y, rotation.z
    scalar = rotation.w
    dot_uv = ux * value.x + uy * value.y + uz * value.z
    dot_uu = ux * ux + uy * uy + uz * uz
    cross_x = uy * value.z - uz * value.y
    cross_y = uz * value.x - ux * value.z
    cross_z = ux * value.y - uy * value.x
    return Vector3(
        2 * dot_uv * ux + (scalar * scalar - dot_uu) * value.x + 2 * scalar * cross_x,
        2 * dot_uv * uy + (scalar * scalar - dot_uu) * value.y + 2 * scalar * cross_y,
        2 * dot_uv * uz + (scalar * scalar - dot_uu) * value.z + 2 * scalar * cross_z,
    )


def _translate(transform: JointTransform, local: Vector3) -> Vector3:
    offset = _rotate(transform.rotation, local)
    return Vector3(
        transform.position.x + offset.x,
        transform.position.y + offset.y,
        transform.position.z + offset.z,
    )


def end_effector_world_frame(
    model: CanonicalBodyModel,
    pose: BodyPose,
    end_effector_id: str,
) -> EndEffectorWorldFrame:
    worlds = dict(forward_kinematics(model, pose))
    definition = next(
        (item for item in model.end_effectors if item.end_effector_id == end_effector_id),
        None,
    )
    if definition is None:
        raise BodySolverError(BodySolverFailureCode.UNKNOWN_BODY_REFERENCE)
    joint_world = worlds[definition.joint_id]
    return EndEffectorWorldFrame(
        definition.end_effector_id,
        _translate(joint_world, definition.local_position),
        _rotate(joint_world.rotation, definition.local_forward_axis),
        _rotate(joint_world.rotation, definition.local_up_axis),
    )


def dynamic_center_of_mass(model: CanonicalBodyModel, pose: BodyPose) -> Vector3:
    worlds = dict(forward_kinematics(model, pose))
    if not model.segments:
        raise BodySolverError(BodySolverFailureCode.BALANCE_INFEASIBLE)
    total_mass = 0.0
    weighted_x = 0.0
    weighted_y = 0.0
    weighted_z = 0.0
    for segment in model.segments:
        fraction = segment.center_of_mass_fraction_from_proximal
        if fraction is None:
            raise BodySolverError(BodySolverFailureCode.BALANCE_INFEASIBLE)
        proximal = worlds[segment.proximal_joint_id].position
        distal = worlds[segment.distal_joint_id].position
        center = Vector3(
            proximal.x + fraction * (distal.x - proximal.x),
            proximal.y + fraction * (distal.y - proximal.y),
            proximal.z + fraction * (distal.z - proximal.z),
        )
        total_mass += segment.mass_fraction
        weighted_x += center.x * segment.mass_fraction
        weighted_y += center.y * segment.mass_fraction
        weighted_z += center.z * segment.mass_fraction
    if abs(total_mass - 1.0) > 1e-6:
        raise BodySolverError(BodySolverFailureCode.BALANCE_INFEASIBLE)
    return Vector3(weighted_x / total_mass, weighted_y / total_mass, weighted_z / total_mass)


def support_contact_world_positions(
    model: CanonicalBodyModel,
    pose: BodyPose,
    active_contact_ids: tuple[str, ...],
) -> tuple[tuple[str, Vector3], ...]:
    if len(active_contact_ids) != len(set(active_contact_ids)):
        raise BodySolverError(BodySolverFailureCode.CONTACT_INFEASIBLE)
    worlds = dict(forward_kinematics(model, pose))
    contacts = {item.contact_id: item for item in model.contact_points}
    result: list[tuple[str, Vector3]] = []
    for contact_id in active_contact_ids:
        definition = contacts.get(contact_id)
        if definition is None or not definition.support_capable:
            raise BodySolverError(BodySolverFailureCode.CONTACT_INFEASIBLE)
        result.append(
            (contact_id, _translate(worlds[definition.joint_id], definition.local_position))
        )
    return tuple(result)


def _cross(
    origin: tuple[float, float],
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return (left[0] - origin[0]) * (right[1] - origin[1]) - (
        left[1] - origin[1]
    ) * (right[0] - origin[0])


def _convex_hull(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    unique = sorted(set(points))
    if len(unique) < 3:
        raise BodySolverError(BodySolverFailureCode.INSUFFICIENT_SUPPORT_GEOMETRY)
    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = tuple(lower[:-1] + upper[:-1])
    if len(hull) < 3:
        raise BodySolverError(BodySolverFailureCode.INSUFFICIENT_SUPPORT_GEOMETRY)
    return hull


def _inside_margin(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
    epsilon: float,
) -> float:
    margin = float("inf")
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        edge_x = end[0] - start[0]
        edge_z = end[1] - start[1]
        length = sqrt(edge_x * edge_x + edge_z * edge_z)
        if length <= epsilon:
            raise BodySolverError(BodySolverFailureCode.INSUFFICIENT_SUPPORT_GEOMETRY)
        signed_distance = _cross(start, end, point) / length
        if signed_distance < -epsilon:
            raise BodySolverError(BodySolverFailureCode.BALANCE_INFEASIBLE)
        margin = min(margin, signed_distance)
    return margin


def validate_balance(
    model: CanonicalBodyModel,
    pose: BodyPose,
    balance_mode: BodyBalanceMode,
    active_contact_ids: tuple[str, ...],
    policy: BodySolverPolicy,
) -> BodyBalanceEvidence:
    if not isinstance(balance_mode, BodyBalanceMode):
        raise BodySolverError(BodySolverFailureCode.BALANCE_INFEASIBLE)
    if not isinstance(policy, BodySolverPolicy):
        raise BodySolverError(BodySolverFailureCode.INVALID_SOLVER_POLICY)
    center = dynamic_center_of_mass(model, pose)
    if balance_mode is BodyBalanceMode.TEMPORARY_FLIGHT_ALLOWED:
        return BodyBalanceEvidence(center, (), (), None, False)
    contacts = support_contact_world_positions(model, pose, active_contact_ids)
    hull = _convex_hull(tuple((value.x, value.z) for _, value in contacts))
    margin = _inside_margin((center.x, center.z), hull, policy.numeric_epsilon)
    required_margin = policy.minimum_support_margin_ratio * model.reference_height
    if margin + policy.numeric_epsilon < required_margin:
        raise BodySolverError(BodySolverFailureCode.BALANCE_INFEASIBLE)
    return BodyBalanceEvidence(
        center,
        tuple(contact_id for contact_id, _ in contacts),
        hull,
        margin,
        True,
    )
