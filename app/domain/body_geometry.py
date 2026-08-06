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
