from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from enum import Enum


def _number(value: float, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


class BodyCoordinateSpace(str, Enum):
    """BodyPoseFrameの3D座標系。"""

    RIGHT_HANDED_Y_UP = "right_handed_y_up"


@dataclass(frozen=True, slots=True)
class BodyVector3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

    def normalized(self) -> BodyVector3:
        length = math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)
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
        values = tuple(_finite(getattr(self, name), name) for name in ("x", "y", "z", "w"))
        length = math.sqrt(sum(value * value for value in values))
        if length <= 1e-9:
            raise ValueError("quaternion must not be zero")
        for name, value in zip(("x", "y", "z", "w"), values):
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

        cx, sx = math.cos(x / 2.0), math.sin(x / 2.0)
        cy, sy = math.cos(y / 2.0), math.sin(y / 2.0)
        cz, sz = math.cos(z / 2.0), math.sin(z / 2.0)
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
    scale: BodyVector3 = field(default_factory=lambda: BodyVector3(1.0, 1.0, 1.0))

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
class BodyJointPose:
    """Canonical jointのローカル姿勢。3D Adapterがモデル骨へ割り当てる。"""

    joint_id: str
    rotation: BodyQuaternion = field(default_factory=BodyQuaternion)
    position: BodyVector3 | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        joint_id = self.joint_id.strip().lower()
        if not joint_id or len(joint_id) > 80:
            raise ValueError("joint_id must contain 1 to 80 characters")
        object.__setattr__(self, "joint_id", joint_id)
        object.__setattr__(
            self,
            "confidence",
            _number(self.confidence, "confidence", 0.0, 1.0),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "joint_id": self.joint_id,
            "rotation": self.rotation.as_payload(),
            "position": self.position.as_payload() if self.position is not None else None,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class BodyBlendShape:
    """顔・目・口のモデル非依存BlendShape値。"""

    name: str
    value: float

    def __post_init__(self) -> None:
        name = self.name.strip().lower()
        if not name or len(name) > 80:
            raise ValueError("blend shape name has invalid length")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", _number(self.value, "value", 0.0, 1.0))

    def as_payload(self) -> dict[str, object]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class BodyGazeVector:
    """3D空間上の視線Ray。"""

    origin: BodyVector3 = field(default_factory=lambda: BodyVector3(0.0, 1.55, 0.0))
    direction: BodyVector3 = field(default_factory=lambda: BodyVector3(0.0, 0.0, 1.0))

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", self.direction.normalized())

    def as_payload(self) -> dict[str, object]:
        return {
            "origin": self.origin.as_payload(),
            "direction": self.direction.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class BodyInnerMotionState:
    """身体運動へ投影する、エンジン非依存の内的状態。"""

    arousal: float = 0.35
    tension: float = 0.2
    curiosity: float = 0.4
    confidence: float = 0.5
    engagement: float = 0.5
    avoidance: float = 0.0
    movement_energy: float = 0.35

    def __post_init__(self) -> None:
        for value_field in fields(self):
            object.__setattr__(
                self,
                value_field.name,
                _number(getattr(self, value_field.name), value_field.name, 0.0, 1.0),
            )

    def as_payload(self) -> dict[str, float]:
        return {value_field.name: getattr(self, value_field.name) for value_field in fields(self)}


@dataclass(frozen=True, slots=True)
class BodyAttentionCandidate:
    """PerceptionからBodyへ渡される注視候補。座標は正規化画面空間。"""

    candidate_id: str
    x: float
    y: float
    salience: float = 0.5
    novelty: float = 0.0
    threat: float = 0.0
    relevance: float = 0.5
    stability: float = 0.7

    def __post_init__(self) -> None:
        candidate_id = self.candidate_id.strip()
        if not candidate_id or len(candidate_id) > 80:
            raise ValueError("candidate_id must contain 1 to 80 characters")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "x", _number(self.x, "x", -1.0, 1.0))
        object.__setattr__(self, "y", _number(self.y, "y", -1.0, 1.0))
        for name in ("salience", "novelty", "threat", "relevance", "stability"):
            object.__setattr__(
                self,
                name,
                _number(getattr(self, name), name, 0.0, 1.0),
            )

    def as_payload(self) -> dict[str, float | str]:
        return {
            "candidate_id": self.candidate_id,
            "x": self.x,
            "y": self.y,
            "salience": self.salience,
            "novelty": self.novelty,
            "threat": self.threat,
            "relevance": self.relevance,
            "stability": self.stability,
        }


@dataclass(frozen=True, slots=True)
class BodyTrackingPose:
    """2D・Live2D向けの正規化補助投影。汎用3D骨格の代替ではない。"""

    head_yaw: float = 0.0
    head_pitch: float = 0.0
    head_roll: float = 0.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    eye_left_open: float = 1.0
    eye_right_open: float = 1.0
    mouth_open: float = 0.0
    mouth_form: float = 0.0
    torso_yaw: float = 0.0
    torso_pitch: float = 0.0
    torso_roll: float = 0.0
    body_height: float = 0.0
    left_arm_raise: float = 0.0
    right_arm_raise: float = 0.0
    left_arm_in: float = 0.0
    right_arm_in: float = 0.0

    def __post_init__(self) -> None:
        unit_fields = {
            "eye_left_open",
            "eye_right_open",
            "mouth_open",
            "left_arm_raise",
            "right_arm_raise",
        }
        for value_field in fields(self):
            minimum, maximum = ((0.0, 1.0) if value_field.name in unit_fields else (-1.0, 1.0))
            object.__setattr__(
                self,
                value_field.name,
                _number(getattr(self, value_field.name), value_field.name, minimum, maximum),
            )

    def as_payload(self) -> dict[str, float]:
        return {value_field.name: getattr(self, value_field.name) for value_field in fields(self)}


@dataclass(frozen=True, slots=True)
class BodyTrackingVelocity:
    """正規化補助軸の毎秒変化量。"""

    head_yaw: float = 0.0
    head_pitch: float = 0.0
    head_roll: float = 0.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    eye_left_open: float = 0.0
    eye_right_open: float = 0.0
    mouth_open: float = 0.0
    mouth_form: float = 0.0
    torso_yaw: float = 0.0
    torso_pitch: float = 0.0
    torso_roll: float = 0.0
    body_height: float = 0.0
    left_arm_raise: float = 0.0
    right_arm_raise: float = 0.0
    left_arm_in: float = 0.0
    right_arm_in: float = 0.0

    def __post_init__(self) -> None:
        for value_field in fields(self):
            object.__setattr__(
                self,
                value_field.name,
                _number(getattr(self, value_field.name), value_field.name, -8.0, 8.0),
            )

    def as_payload(self) -> dict[str, float]:
        return {value_field.name: getattr(self, value_field.name) for value_field in fields(self)}


@dataclass(frozen=True, slots=True)
class BodyPoseFrame:
    """Body Controllerが一定周期で出力する汎用トラッキングフレーム。

    root_transform・joints・blend_shapes・gaze_vectorが3D向けの主契約で、
    pose・velocityは棒人間／Live2D Adapter向けの補助投影である。
    """

    sequence: int
    timestamp_ms: int
    pose: BodyTrackingPose
    velocity: BodyTrackingVelocity
    inner_state: BodyInnerMotionState
    root_transform: BodyTransform3D = field(default_factory=BodyTransform3D)
    joints: tuple[BodyJointPose, ...] = ()
    blend_shapes: tuple[BodyBlendShape, ...] = ()
    gaze_vector: BodyGazeVector = field(default_factory=BodyGazeVector)
    coordinate_space: BodyCoordinateSpace = BodyCoordinateSpace.RIGHT_HANDED_Y_UP
    attention_target_id: str | None = None
    attention_dwell_ms: int = 0
    schema_version: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")
        if isinstance(self.timestamp_ms, bool) or not isinstance(self.timestamp_ms, int):
            raise TypeError("timestamp_ms must be an integer")
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must not be negative")
        if isinstance(self.attention_dwell_ms, bool) or not isinstance(
            self.attention_dwell_ms, int
        ):
            raise TypeError("attention_dwell_ms must be an integer")
        if self.attention_dwell_ms < 0:
            raise ValueError("attention_dwell_ms must not be negative")
        if self.attention_target_id is not None:
            target = self.attention_target_id.strip()
            if not target or len(target) > 80:
                raise ValueError("attention_target_id has invalid length")
            object.__setattr__(self, "attention_target_id", target)
        joint_ids = [joint.joint_id for joint in self.joints]
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("joint ids must be unique")
        shape_names = [shape.name for shape in self.blend_shapes]
        if len(shape_names) != len(set(shape_names)):
            raise ValueError("blend shape names must be unique")

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "timestamp_ms": self.timestamp_ms,
            "coordinate_space": self.coordinate_space.value,
            "root_transform": self.root_transform.as_payload(),
            "joints": [joint.as_payload() for joint in self.joints],
            "blend_shapes": [shape.as_payload() for shape in self.blend_shapes],
            "gaze_vector": self.gaze_vector.as_payload(),
            "pose": self.pose.as_payload(),
            "velocity": self.velocity.as_payload(),
            "inner_state": self.inner_state.as_payload(),
            "attention_target_id": self.attention_target_id,
            "attention_dwell_ms": self.attention_dwell_ms,
        }
