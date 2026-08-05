from __future__ import annotations

from dataclasses import dataclass, fields


def _number(value: float, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


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
        for field in fields(self):
            object.__setattr__(
                self,
                field.name,
                _number(getattr(self, field.name), field.name, 0.0, 1.0),
            )

    def as_payload(self) -> dict[str, float]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


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
    """Live2D・3D・棒人間へ共通送信する正規化トラッキング姿勢。"""

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
        for field in fields(self):
            minimum, maximum = ((0.0, 1.0) if field.name in unit_fields else (-1.0, 1.0))
            object.__setattr__(
                self,
                field.name,
                _number(getattr(self, field.name), field.name, minimum, maximum),
            )

    def as_payload(self) -> dict[str, float]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class BodyTrackingVelocity:
    """各正規化軸の毎秒変化量。"""

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
        for field in fields(self):
            object.__setattr__(
                self,
                field.name,
                _number(getattr(self, field.name), field.name, -8.0, 8.0),
            )

    def as_payload(self) -> dict[str, float]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class BodyPoseFrame:
    """Body Controllerが一定周期で出力するトラッキングフレーム。"""

    sequence: int
    timestamp_ms: int
    pose: BodyTrackingPose
    velocity: BodyTrackingVelocity
    inner_state: BodyInnerMotionState
    attention_target_id: str | None = None
    attention_dwell_ms: int = 0
    schema_version: int = 1

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

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "timestamp_ms": self.timestamp_ms,
            "pose": self.pose.as_payload(),
            "velocity": self.velocity.as_payload(),
            "inner_state": self.inner_state.as_payload(),
            "attention_target_id": self.attention_target_id,
            "attention_dwell_ms": self.attention_dwell_ms,
        }
