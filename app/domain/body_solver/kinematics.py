from __future__ import annotations

from math import sqrt

from app.domain.body import (
    BodyPose,
    CanonicalBodyModel,
    JointTransform,
    Quaternion,
    Vector3,
)


def _multiply_rotation(left: Quaternion, right: Quaternion) -> Quaternion:
    x = left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y
    y = left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x
    z = left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w
    w = left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z
    magnitude = sqrt(x * x + y * y + z * z + w * w)
    if magnitude == 0:
        raise ValueError("rotation合成結果を正規化できません")
    return Quaternion(x / magnitude, y / magnitude, z / magnitude, w / magnitude)


def _rotate_vector(rotation: Quaternion, value: Vector3) -> Vector3:
    # 単位quaternionによる q * v * q^-1 を展開して余分なQuaternion生成を避ける。
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


def _compose(parent: JointTransform, local: JointTransform) -> JointTransform:
    offset = _rotate_vector(parent.rotation, local.position)
    position = Vector3(
        parent.position.x + offset.x,
        parent.position.y + offset.y,
        parent.position.z + offset.z,
    )
    return JointTransform(position, _multiply_rotation(parent.rotation, local.rotation))


def forward_kinematics(
    model: CanonicalBodyModel,
    pose: BodyPose,
) -> tuple[tuple[str, JointTransform], ...]:
    """Canonical local poseだけから全jointのworld transformを決定論的に求める。"""

    if not isinstance(model, CanonicalBodyModel):
        raise ValueError("model は CanonicalBodyModel でなければなりません")
    if not isinstance(pose, BodyPose):
        raise ValueError("pose は BodyPose でなければなりません")
    pose.validate_for(model)

    definitions = {joint.joint_id: joint for joint in model.joints}
    local_transforms = dict(pose.joint_local_transforms)
    resolved: dict[str, JointTransform] = {
        model.root_joint_id: pose.root_world_transform,
    }

    def resolve(joint_id: str) -> JointTransform:
        current = resolved.get(joint_id)
        if current is not None:
            return current
        definition = definitions[joint_id]
        parent_id = definition.parent_joint_id
        if parent_id is None:
            raise ValueError("root以外のjointに親がありません")
        parent = resolve(parent_id)
        world = _compose(parent, local_transforms[joint_id])
        resolved[joint_id] = world
        return world

    return tuple((joint.joint_id, resolve(joint.joint_id)) for joint in model.joints)
