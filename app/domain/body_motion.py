from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _bounded(value: float, name: str, minimum: float, maximum: float) -> float:
    normalized = _finite(value, name)
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


class BodyMotionOperation(str, Enum):
    """完成動作名ではなく、Bodyが組み合わせる運動プリミティブ。"""

    REACH = "reach"
    TRANSLATE = "translate"
    ROTATE = "rotate"
    OSCILLATE = "oscillate"
    CIRCLE = "circle"
    HOLD = "hold"
    RELEASE = "release"
    SEQUENCE = "sequence"
    PARALLEL = "parallel"
    REPEAT = "repeat"


class BodyMotionEasing(str, Enum):
    LINEAR = "linear"
    SMOOTHSTEP = "smoothstep"
    EASE_IN_OUT = "ease_in_out"


@dataclass(frozen=True, slots=True)
class BodyMotionVector:
    """Bodyローカル座標。x=右、y=上、z=前。値は体格で正規化する。"""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    def scaled(self, factor: float) -> BodyMotionVector:
        normalized = _finite(factor, "factor")
        return BodyMotionVector(
            self.x * normalized,
            self.y * normalized,
            self.z * normalized,
        )

    def as_payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_payload(cls, payload: object) -> BodyMotionVector:
        if not isinstance(payload, dict):
            raise ValueError("vector must be an object")
        return cls(
            x=float(payload.get("x", 0.0)),
            y=float(payload.get("y", 0.0)),
            z=float(payload.get("z", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class BodyMotionTiming:
    duration_seconds: float = 1.0
    delay_seconds: float = 0.0
    repetitions: int = 1
    easing: BodyMotionEasing = BodyMotionEasing.SMOOTHSTEP
    hold_final: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "duration_seconds",
            _bounded(self.duration_seconds, "duration_seconds", 0.05, 120.0),
        )
        object.__setattr__(
            self,
            "delay_seconds",
            _bounded(self.delay_seconds, "delay_seconds", 0.0, 120.0),
        )
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int):
            raise TypeError("repetitions must be an integer")
        if not 1 <= self.repetitions <= 64:
            raise ValueError("repetitions must be between 1 and 64")
        if not isinstance(self.easing, BodyMotionEasing):
            object.__setattr__(self, "easing", BodyMotionEasing(str(self.easing)))
        if not isinstance(self.hold_final, bool):
            raise TypeError("hold_final must be a boolean")

    @property
    def total_seconds(self) -> float:
        return self.delay_seconds + self.duration_seconds

    def as_payload(self) -> dict[str, object]:
        return {
            "duration_seconds": self.duration_seconds,
            "delay_seconds": self.delay_seconds,
            "repetitions": self.repetitions,
            "easing": self.easing.value,
            "hold_final": self.hold_final,
        }

    @classmethod
    def from_payload(cls, payload: object) -> BodyMotionTiming:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("timing must be an object")
        return cls(
            duration_seconds=float(payload.get("duration_seconds", 1.0)),
            delay_seconds=float(payload.get("delay_seconds", 0.0)),
            repetitions=int(payload.get("repetitions", 1)),
            easing=BodyMotionEasing(
                str(payload.get("easing", BodyMotionEasing.SMOOTHSTEP.value))
            ),
            hold_final=bool(payload.get("hold_final", False)),
        )


@dataclass(frozen=True, slots=True)
class BodyMotionRequest:
    """Brain／入力意味解析からBodyへ渡すモデル非依存の運動要求。

    `right_hand_raise`のような完成動作名は持たない。対象、軌道、量、時間、
    合成順序を運動プリミティブとして表す。
    """

    operation: BodyMotionOperation
    target: str | None = None
    vector: BodyMotionVector | None = None
    pivot: str | None = None
    axis: str = "z"
    amount: float = 0.0
    radius: float = 0.0
    direction: int = 1
    timing: BodyMotionTiming = field(default_factory=BodyMotionTiming)
    children: tuple[BodyMotionRequest, ...] = ()
    motion_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.operation, BodyMotionOperation):
            object.__setattr__(
                self,
                "operation",
                BodyMotionOperation(str(self.operation).strip().lower()),
            )
        target = self.target.strip().lower() if isinstance(self.target, str) else None
        pivot = self.pivot.strip().lower() if isinstance(self.pivot, str) else None
        axis = self.axis.strip().lower()
        motion_id = (
            self.motion_id.strip()
            if isinstance(self.motion_id, str) and self.motion_id.strip()
            else None
        )
        if target is not None and len(target) > 80:
            raise ValueError("target is too long")
        if pivot is not None and len(pivot) > 80:
            raise ValueError("pivot is too long")
        if axis not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z")
        if motion_id is not None and len(motion_id) > 120:
            raise ValueError("motion_id is too long")
        if self.direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "pivot", pivot)
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "motion_id", motion_id)
        object.__setattr__(self, "amount", _finite(self.amount, "amount"))
        object.__setattr__(self, "radius", _bounded(self.radius, "radius", 0.0, 4.0))
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "metadata", dict(self.metadata))
        self._validate_shape()

    def _validate_shape(self) -> None:
        composite = {
            BodyMotionOperation.SEQUENCE,
            BodyMotionOperation.PARALLEL,
            BodyMotionOperation.REPEAT,
        }
        if self.operation in composite:
            if not self.children:
                raise ValueError(f"{self.operation.value} requires children")
            if self.operation is BodyMotionOperation.REPEAT and len(self.children) != 1:
                raise ValueError("repeat requires exactly one child")
            return
        if self.children:
            raise ValueError(f"{self.operation.value} must not contain children")
        if self.operation in {BodyMotionOperation.HOLD, BodyMotionOperation.RELEASE}:
            if self.target is None:
                raise ValueError(f"{self.operation.value} requires target")
            return
        if self.target is None:
            raise ValueError(f"{self.operation.value} requires target")
        if self.operation in {
            BodyMotionOperation.REACH,
            BodyMotionOperation.TRANSLATE,
            BodyMotionOperation.OSCILLATE,
        } and self.vector is None:
            raise ValueError(f"{self.operation.value} requires vector")
        if self.operation is BodyMotionOperation.CIRCLE and self.radius <= 0.0:
            raise ValueError("circle requires radius greater than zero")
        if self.operation is BodyMotionOperation.ROTATE and abs(self.amount) <= 1e-9:
            raise ValueError("rotate requires non-zero amount")

    def as_payload(self) -> dict[str, object]:
        return {
            "operation": self.operation.value,
            "target": self.target,
            "vector": self.vector.as_payload() if self.vector is not None else None,
            "pivot": self.pivot,
            "axis": self.axis,
            "amount": self.amount,
            "radius": self.radius,
            "direction": self.direction,
            "timing": self.timing.as_payload(),
            "children": [child.as_payload() for child in self.children],
            "motion_id": self.motion_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: object) -> BodyMotionRequest:
        if not isinstance(payload, dict):
            raise ValueError("motion request must be an object")
        raw_children = payload.get("children", ())
        if raw_children is None:
            raw_children = ()
        if not isinstance(raw_children, (list, tuple)):
            raise ValueError("children must be an array")
        vector_payload = payload.get("vector")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        return cls(
            operation=BodyMotionOperation(str(payload.get("operation", ""))),
            target=(
                str(payload["target"])
                if payload.get("target") is not None
                else None
            ),
            vector=(
                BodyMotionVector.from_payload(vector_payload)
                if vector_payload is not None
                else None
            ),
            pivot=(
                str(payload["pivot"])
                if payload.get("pivot") is not None
                else None
            ),
            axis=str(payload.get("axis", "z")),
            amount=float(payload.get("amount", 0.0)),
            radius=float(payload.get("radius", 0.0)),
            direction=int(payload.get("direction", 1)),
            timing=BodyMotionTiming.from_payload(payload.get("timing")),
            children=tuple(cls.from_payload(child) for child in raw_children),
            motion_id=(
                str(payload["motion_id"])
                if payload.get("motion_id") is not None
                else None
            ),
            metadata={str(key): value for key, value in metadata.items()},
        )


@dataclass(frozen=True, slots=True)
class BodyMotionPlan:
    """BodyMotionPlannerが検証・正規化した実行計画。"""

    plan_id: str
    root: BodyMotionRequest
    duration_seconds: float
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        plan_id = self.plan_id.strip()
        if not plan_id:
            raise ValueError("plan_id must not be empty")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(
            self,
            "duration_seconds",
            _bounded(self.duration_seconds, "duration_seconds", 0.0, 7_680.0),
        )
        object.__setattr__(self, "targets", tuple(dict.fromkeys(self.targets)))

    def as_payload(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "duration_seconds": self.duration_seconds,
            "targets": list(self.targets),
            "root": self.root.as_payload(),
        }


def payload_dict(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    return {str(key): nested for key, nested in value.items()}
