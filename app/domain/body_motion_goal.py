from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

from app.domain.body_geometry import BodyQuaternion, BodyVector3
from app.domain.body_value_validation import (
    bounded_number,
    non_negative_integer,
    normalized_identifier,
)


class BodyMotionGoalKind(str, Enum):
    END_EFFECTOR_POSITION = "end_effector_position"
    LOOK_DIRECTION = "look_direction"
    JOINT_ORIENTATION = "joint_orientation"
    ROOT_TRANSLATION = "root_translation"
    CROUCH = "crouch"
    JUMP = "jump"
    OSCILLATE = "oscillate"
    COMPOSITE = "composite"


@dataclass(frozen=True, slots=True)
class BodyMotionGoal:
    """Bodyが解くモデル非依存の高レベル運動目標。

    完成Pose名やAvatar固有Bone名を含めない。position/direction/orientationは
    Body座標系（right-handed, Y-up）の意味目標であり、実関節角はPlanner/Solverが決める。
    directionは単位球面上の任意3D方向、orientationはQuaternionで表現する。
    """

    kind: BodyMotionGoalKind
    target_id: str | None = None
    position: BodyVector3 | None = None
    direction: BodyVector3 | None = None
    orientation: BodyQuaternion | None = None
    magnitude: float = 1.0
    duration_ms: int = 1200
    weight: float = 1.0
    cycles: float = 1.0
    components: tuple[BodyMotionGoal, ...] = ()
    goal_id: str = ""

    def __post_init__(self) -> None:
        kind = self.kind
        if isinstance(kind, str):
            kind = BodyMotionGoalKind(kind)
        if not isinstance(kind, BodyMotionGoalKind):
            raise TypeError("kind must be BodyMotionGoalKind")
        object.__setattr__(self, "kind", kind)

        goal_id = self.goal_id or f"body-motion-{uuid4()}"
        object.__setattr__(
            self,
            "goal_id",
            normalized_identifier(goal_id, "goal_id", maximum_length=128),
        )

        if self.target_id is not None:
            object.__setattr__(
                self,
                "target_id",
                normalized_identifier(
                    self.target_id,
                    "target_id",
                    lowercase=True,
                    maximum_length=80,
                ),
            )
        for name in ("position", "direction"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, BodyVector3):
                raise TypeError(f"{name} must be BodyVector3 or None")
        if self.orientation is not None and not isinstance(
            self.orientation, BodyQuaternion
        ):
            raise TypeError("orientation must be BodyQuaternion or None")
        if self.direction is not None:
            object.__setattr__(self, "direction", self.direction.normalized())

        object.__setattr__(
            self,
            "magnitude",
            bounded_number(self.magnitude, "magnitude", 0.0, 1.0),
        )
        object.__setattr__(
            self,
            "weight",
            bounded_number(self.weight, "weight", 0.0, 1.0),
        )
        duration = non_negative_integer(self.duration_ms, "duration_ms")
        if not 120 <= duration <= 30_000:
            raise ValueError("duration_ms must be between 120 and 30000")
        object.__setattr__(self, "duration_ms", duration)
        if isinstance(self.cycles, bool) or not isinstance(self.cycles, (int, float)):
            raise TypeError("cycles must be a number")
        cycles = float(self.cycles)
        if not 0.25 <= cycles <= 20.0:
            raise ValueError("cycles must be between 0.25 and 20.0")
        object.__setattr__(self, "cycles", cycles)

        components = tuple(self.components)
        if not all(isinstance(value, BodyMotionGoal) for value in components):
            raise TypeError("components must contain BodyMotionGoal values")
        if len(components) > 8:
            raise ValueError("components must contain at most 8 goals")
        if any(value.components for value in components):
            raise ValueError("nested composite body motion goals are not supported")
        object.__setattr__(self, "components", components)

        self._validate_shape()

    def _validate_shape(self) -> None:
        kind = self.kind
        if kind is BodyMotionGoalKind.COMPOSITE:
            if len(self.components) < 2:
                raise ValueError("composite goal must contain at least two components")
            return
        if self.components:
            raise ValueError("components are only valid for composite goals")

        if kind is BodyMotionGoalKind.END_EFFECTOR_POSITION:
            if self.target_id is None or self.position is None:
                raise ValueError("end-effector goal requires target_id and position")
        elif kind is BodyMotionGoalKind.LOOK_DIRECTION:
            if self.direction is None:
                raise ValueError("look-direction goal requires direction")
        elif kind is BodyMotionGoalKind.JOINT_ORIENTATION:
            if self.target_id is None or self.orientation is None:
                raise ValueError("joint-orientation goal requires target_id and orientation")
        elif kind is BodyMotionGoalKind.ROOT_TRANSLATION:
            if self.position is None:
                raise ValueError("root-translation goal requires position")
        elif kind in {BodyMotionGoalKind.CROUCH, BodyMotionGoalKind.JUMP}:
            if self.target_id is not None:
                raise ValueError(f"{kind.value} does not use target_id")
        elif kind is BodyMotionGoalKind.OSCILLATE:
            if self.target_id is None:
                raise ValueError("oscillate goal requires target_id")
            if self.direction is None and self.orientation is None:
                raise ValueError("oscillate goal requires direction or orientation")

    @classmethod
    def composite(
        cls,
        *components: BodyMotionGoal,
        duration_ms: int | None = None,
        weight: float = 1.0,
    ) -> BodyMotionGoal:
        if len(components) < 2:
            raise ValueError("composite requires at least two components")
        return cls(
            kind=BodyMotionGoalKind.COMPOSITE,
            components=tuple(components),
            duration_ms=(
                max(value.duration_ms for value in components)
                if duration_ms is None
                else duration_ms
            ),
            weight=weight,
        )


__all__ = ["BodyMotionGoal", "BodyMotionGoalKind"]
