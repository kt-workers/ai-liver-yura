from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from app.domain.body_value_validation import finite_number


class BodyCoordinateSpace(str, Enum):
    """BodyPoseFrameが使用するモデル非依存の3D座標系。"""

    RIGHT_HANDED_Y_UP = "right_handed_y_up"


@dataclass(frozen=True, slots=True)
class BodyVector3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            object.__setattr__(
                self,
                name,
                finite_number(getattr(self, name), name),
            )

    @property
    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalized(self) -> BodyVector3:
        length = self.length
        if length <= 1e-9:
            raise ValueError("zero vector cannot be normalized")
        return BodyVector3(self.x / length, self.y / length, self.z / length)

    def dot(self, other: BodyVector3) -> float:
        if not isinstance(other, BodyVector3):
            raise TypeError("other must be BodyVector3")
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: BodyVector3) -> BodyVector3:
        if not isinstance(other, BodyVector3):
            raise TypeError("other must be BodyVector3")
        return BodyVector3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def added(self, other: BodyVector3) -> BodyVector3:
        if not isinstance(other, BodyVector3):
            raise TypeError("other must be BodyVector3")
        return BodyVector3(self.x + other.x, self.y + other.y, self.z + other.z)

    def subtracted(self, other: BodyVector3) -> BodyVector3:
        if not isinstance(other, BodyVector3):
            raise TypeError("other must be BodyVector3")
        return BodyVector3(self.x - other.x, self.y - other.y, self.z - other.z)

    def scaled(self, value: float) -> BodyVector3:
        scale = finite_number(value, "scale")
        return BodyVector3(self.x * scale, self.y * scale, self.z * scale)

    def lerp(self, other: BodyVector3, ratio: float) -> BodyVector3:
        if not isinstance(other, BodyVector3):
            raise TypeError("other must be BodyVector3")
        t = finite_number(ratio, "ratio")
        if not 0.0 <= t <= 1.0:
            raise ValueError("ratio must be between 0 and 1")
        return BodyVector3(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
            self.z + (other.z - self.z) * t,
        )

    def as_payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True, slots=True)
class BodyQuaternion:
    """モデル非依存の正規化Quaternion。"""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

    def __post_init__(self) -> None:
        names = ("x", "y", "z", "w")
        values = tuple(finite_number(getattr(self, name), name) for name in names)
        length = math.sqrt(sum(value * value for value in values))
        if length <= 1e-9:
            raise ValueError("quaternion must not be zero")
        for name, value in zip(names, values):
            object.__setattr__(self, name, value / length)

    @classmethod
    def from_euler_radians(
        cls,
        *,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> BodyQuaternion:
        """XYZ Euler角からQuaternionを生成する。"""

        normalized_x = finite_number(x, "x")
        normalized_y = finite_number(y, "y")
        normalized_z = finite_number(z, "z")
        cx, sx = math.cos(normalized_x / 2.0), math.sin(normalized_x / 2.0)
        cy, sy = math.cos(normalized_y / 2.0), math.sin(normalized_y / 2.0)
        cz, sz = math.cos(normalized_z / 2.0), math.sin(normalized_z / 2.0)
        return cls(
            x=sx * cy * cz - cx * sy * sz,
            y=cx * sy * cz + sx * cy * sz,
            z=cx * cy * sz - sx * sy * cz,
            w=cx * cy * cz + sx * sy * sz,
        )

    @classmethod
    def from_axis_angle(
        cls,
        axis: BodyVector3,
        radians: float,
    ) -> BodyQuaternion:
        if not isinstance(axis, BodyVector3):
            raise TypeError("axis must be BodyVector3")
        normalized_axis = axis.normalized()
        angle = finite_number(radians, "radians")
        half = angle / 2.0
        scale = math.sin(half)
        return cls(
            x=normalized_axis.x * scale,
            y=normalized_axis.y * scale,
            z=normalized_axis.z * scale,
            w=math.cos(half),
        )

    @classmethod
    def from_two_vectors(
        cls,
        source: BodyVector3,
        target: BodyVector3,
    ) -> BodyQuaternion:
        """sourceをtargetへ最短回転するQuaternionを生成する。"""

        if not isinstance(source, BodyVector3) or not isinstance(target, BodyVector3):
            raise TypeError("source and target must be BodyVector3")
        source_n = source.normalized()
        target_n = target.normalized()
        dot = max(-1.0, min(1.0, source_n.dot(target_n)))
        if dot >= 1.0 - 1e-9:
            return cls()
        if dot <= -1.0 + 1e-9:
            basis = (
                BodyVector3(1.0, 0.0, 0.0)
                if abs(source_n.x) < 0.8
                else BodyVector3(0.0, 1.0, 0.0)
            )
            axis = source_n.cross(basis)
            if axis.length <= 1e-9:
                axis = source_n.cross(BodyVector3(0.0, 0.0, 1.0))
            return cls.from_axis_angle(axis, math.pi)
        cross = source_n.cross(target_n)
        return cls(x=cross.x, y=cross.y, z=cross.z, w=1.0 + dot)

    def conjugated(self) -> BodyQuaternion:
        return BodyQuaternion(-self.x, -self.y, -self.z, self.w)

    def multiplied(self, other: BodyQuaternion) -> BodyQuaternion:
        if not isinstance(other, BodyQuaternion):
            raise TypeError("other must be BodyQuaternion")
        return BodyQuaternion(
            w=self.w * other.w - self.x * other.x - self.y * other.y - self.z * other.z,
            x=self.w * other.x + self.x * other.w + self.y * other.z - self.z * other.y,
            y=self.w * other.y - self.x * other.z + self.y * other.w + self.z * other.x,
            z=self.w * other.z + self.x * other.y - self.y * other.x + self.z * other.w,
        )

    def rotate_vector(self, value: BodyVector3) -> BodyVector3:
        """Quaternion回転を3D Vectorへ適用する。"""

        if not isinstance(value, BodyVector3):
            raise TypeError("value must be BodyVector3")
        axis = BodyVector3(self.x, self.y, self.z)
        axis_dot = axis.dot(value)
        axis_length_sq = axis.dot(axis)
        return axis.scaled(2.0 * axis_dot).added(
            value.scaled(self.w * self.w - axis_length_sq)
        ).added(axis.cross(value).scaled(2.0 * self.w))

    def slerp(self, other: BodyQuaternion, ratio: float) -> BodyQuaternion:
        if not isinstance(other, BodyQuaternion):
            raise TypeError("other must be BodyQuaternion")
        t = finite_number(ratio, "ratio")
        if not 0.0 <= t <= 1.0:
            raise ValueError("ratio must be between 0 and 1")
        dot = self.x * other.x + self.y * other.y + self.z * other.z + self.w * other.w
        tx, ty, tz, tw = other.x, other.y, other.z, other.w
        if dot < 0.0:
            dot = -dot
            tx, ty, tz, tw = -tx, -ty, -tz, -tw
        dot = max(-1.0, min(1.0, dot))
        if dot > 0.9995:
            return BodyQuaternion(
                self.x + (tx - self.x) * t,
                self.y + (ty - self.y) * t,
                self.z + (tz - self.z) * t,
                self.w + (tw - self.w) * t,
            )
        theta_0 = math.acos(dot)
        sin_theta_0 = math.sin(theta_0)
        theta = theta_0 * t
        s0 = math.sin(theta_0 - theta) / sin_theta_0
        s1 = math.sin(theta) / sin_theta_0
        return BodyQuaternion(
            self.x * s0 + tx * s1,
            self.y * s0 + ty * s1,
            self.z * s0 + tz * s1,
            self.w * s0 + tw * s1,
        )

    def to_euler_radians(self) -> BodyVector3:
        """Joint Limit適用用のXYZ Euler角へ変換する。"""

        sin_x_cos_y = 2.0 * (self.w * self.x + self.y * self.z)
        cos_x_cos_y = 1.0 - 2.0 * (self.x * self.x + self.y * self.y)
        x = math.atan2(sin_x_cos_y, cos_x_cos_y)

        sin_y = 2.0 * (self.w * self.y - self.z * self.x)
        y = (
            math.copysign(math.pi / 2.0, sin_y)
            if abs(sin_y) >= 1.0
            else math.asin(sin_y)
        )

        sin_z_cos_y = 2.0 * (self.w * self.z + self.x * self.y)
        cos_z_cos_y = 1.0 - 2.0 * (self.y * self.y + self.z * self.z)
        z = math.atan2(sin_z_cos_y, cos_z_cos_y)
        return BodyVector3(x, y, z)

    def as_payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}


@dataclass(frozen=True, slots=True)
class BodyTransform3D:
    position: BodyVector3 = field(default_factory=BodyVector3)
    rotation: BodyQuaternion = field(default_factory=BodyQuaternion)
    scale: BodyVector3 = field(
        default_factory=lambda: BodyVector3(1.0, 1.0, 1.0)
    )

    def __post_init__(self) -> None:
        if self.scale.x <= 0.0 or self.scale.y <= 0.0 or self.scale.z <= 0.0:
            raise ValueError("transform scale must be positive")

    def as_payload(self) -> dict[str, object]:
        return {
            "position": self.position.as_payload(),
            "rotation": self.rotation.as_payload(),
            "scale": self.scale.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class BodyGazeVector:
    """3D空間上のモデル非依存な視線Ray。"""

    origin: BodyVector3 = field(
        default_factory=lambda: BodyVector3(0.0, 1.55, 0.0)
    )
    direction: BodyVector3 = field(
        default_factory=lambda: BodyVector3(0.0, 0.0, 1.0)
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", self.direction.normalized())

    def as_payload(self) -> dict[str, object]:
        return {
            "origin": self.origin.as_payload(),
            "direction": self.direction.as_payload(),
        }
