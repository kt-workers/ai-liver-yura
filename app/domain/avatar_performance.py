from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AvatarInterruptPolicy(str, Enum):
    """Avatar Runtimeが既存Performanceと競合した際の高レベル方針。"""

    REPLACE_LOWER_PRIORITY = "replace_lower_priority"
    QUEUE = "queue"
    IGNORE_IF_BUSY = "ignore_if_busy"


class AvatarReturnBehavior(str, Enum):
    """Performance終了後にAvatar Runtimeへ期待する復帰方針。"""

    NEUTRAL = "neutral"
    HOLD = "hold"
    PREVIOUS = "previous"


class AvatarTrackChannel(str, Enum):
    """Avatar Runtime内で独立して合成する演技チャネル。"""

    EXPRESSION = "expression"
    ATTENTION = "attention"
    FACE = "face"
    HEAD = "head"
    TORSO = "torso"
    LEFT_ARM = "left_arm"
    RIGHT_ARM = "right_arm"
    FULL_BODY = "full_body"
    AUTONOMOUS = "autonomous"


class AvatarBlendMode(str, Enum):
    """同じ部位に複数Trackが存在する場合の合成方式。"""

    OVERRIDE = "override"
    ADDITIVE = "additive"


class AvatarContinuity(str, Enum):
    """Track開始時の基準姿勢。"""

    CURRENT = "current"
    NEUTRAL = "neutral"


def _normalize_name(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > 80:
        raise ValueError(f"{field_name} must be 80 characters or fewer")
    return normalized


def _validate_intensity(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    return normalized


def _validate_number_between(
    value: float,
    field_name: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    normalized = float(value)
    if not minimum <= normalized <= maximum:
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return normalized


def _validate_optional_number_between(
    value: float | None,
    field_name: str,
    minimum: float,
    maximum: float,
) -> float | None:
    if value is None:
        return None
    return _validate_number_between(value, field_name, minimum, maximum)


@dataclass(frozen=True, slots=True)
class AvatarExpressionIntent:
    """描画方式に依存しない表情Intent。"""

    name: str
    intensity: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_name(self.name, "expression name"))
        object.__setattr__(
            self,
            "intensity",
            _validate_intensity(self.intensity, "expression intensity"),
        )


@dataclass(frozen=True, slots=True)
class AvatarGestureIntent:
    """旧Segment DTOとの互換用ジェスチャーIntent。"""

    name: str
    intensity: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_name(self.name, "gesture name"))
        object.__setattr__(
            self,
            "intensity",
            _validate_intensity(self.intensity, "gesture intensity"),
        )


@dataclass(frozen=True, slots=True)
class AvatarGazeIntent:
    """対象をどう見るかを表す高レベルな注意Intent。"""

    target: str
    behavior: str = "maintain"
    intensity: float = 1.0
    eye_follow: float = 1.0
    head_follow: float = 0.55
    body_follow: float = 0.15

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _normalize_name(self.target, "gaze target"))
        object.__setattr__(
            self,
            "behavior",
            _normalize_name(self.behavior, "gaze behavior"),
        )
        for field_name in (
            "intensity",
            "eye_follow",
            "head_follow",
            "body_follow",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_intensity(getattr(self, field_name), f"gaze {field_name}"),
            )


@dataclass(frozen=True, slots=True)
class AvatarMotionIntent:
    """周期・軌道を持つ動作を手続き的に生成するためのIntent。"""

    name: str
    intensity: float = 1.0
    amplitude: float = 1.0
    tempo: float = 1.0
    repetitions: int = 1
    body_participation: float = 0.0
    direction: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_name(self.name, "motion name"))
        object.__setattr__(
            self,
            "intensity",
            _validate_intensity(self.intensity, "motion intensity"),
        )
        object.__setattr__(
            self,
            "amplitude",
            _validate_number_between(self.amplitude, "motion amplitude", 0.0, 1.5),
        )
        object.__setattr__(
            self,
            "tempo",
            _validate_number_between(self.tempo, "motion tempo", 0.25, 3.0),
        )
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int):
            raise TypeError("motion repetitions must be an integer")
        if not 1 <= self.repetitions <= 8:
            raise ValueError("motion repetitions must be between 1 and 8")
        object.__setattr__(
            self,
            "body_participation",
            _validate_intensity(
                self.body_participation,
                "motion body_participation",
            ),
        )
        if self.direction is not None:
            object.__setattr__(
                self,
                "direction",
                _normalize_name(self.direction, "motion direction"),
            )


@dataclass(frozen=True, slots=True)
class AvatarPoseIntent:
    """現在姿勢から連続補間するエンジン非依存の正規化姿勢目標。"""

    head_yaw: float | None = None
    head_pitch: float | None = None
    head_roll: float | None = None
    torso_lean_x: float | None = None
    torso_lean_y: float | None = None
    body_height: float | None = None
    gaze_x: float | None = None
    gaze_y: float | None = None
    eye_closure: float | None = None
    mouth_open: float | None = None
    left_arm_raise: float | None = None
    right_arm_raise: float | None = None
    left_arm_in: float | None = None
    right_arm_in: float | None = None
    responsiveness: float = 0.72

    def __post_init__(self) -> None:
        signed_axes = (
            "head_yaw",
            "head_pitch",
            "head_roll",
            "torso_lean_x",
            "torso_lean_y",
            "body_height",
            "gaze_x",
            "gaze_y",
            "left_arm_in",
            "right_arm_in",
        )
        unit_axes = (
            "eye_closure",
            "mouth_open",
            "left_arm_raise",
            "right_arm_raise",
        )
        for field_name in signed_axes:
            object.__setattr__(
                self,
                field_name,
                _validate_optional_number_between(
                    getattr(self, field_name),
                    f"pose {field_name}",
                    -1.0,
                    1.0,
                ),
            )
        for field_name in unit_axes:
            object.__setattr__(
                self,
                field_name,
                _validate_optional_number_between(
                    getattr(self, field_name),
                    f"pose {field_name}",
                    0.0,
                    1.0,
                ),
            )
        object.__setattr__(
            self,
            "responsiveness",
            _validate_number_between(
                self.responsiveness,
                "pose responsiveness",
                0.05,
                1.0,
            ),
        )
        if not any(getattr(self, field_name) is not None for field_name in (*signed_axes, *unit_axes)):
            raise ValueError("pose intent requires at least one target axis")

    def as_payload(self) -> dict[str, float]:
        payload: dict[str, float] = {"responsiveness": self.responsiveness}
        for field_name in (
            "head_yaw",
            "head_pitch",
            "head_roll",
            "torso_lean_x",
            "torso_lean_y",
            "body_height",
            "gaze_x",
            "gaze_y",
            "eye_closure",
            "mouth_open",
            "left_arm_raise",
            "right_arm_raise",
            "left_arm_in",
            "right_arm_in",
        ):
            value = getattr(self, field_name)
            if value is not None:
                payload[field_name] = value
        return payload


@dataclass(frozen=True, slots=True)
class AvatarPerformanceSegment:
    """旧Runtimeとの互換用の直列演技区間。"""

    expression: AvatarExpressionIntent
    gesture: AvatarGestureIntent | None = None
    gaze: AvatarGazeIntent | None = None
    duration_ms: int = 1000
    fade_in_ms: int = 150
    fade_out_ms: int = 250

    def __post_init__(self) -> None:
        _validate_timing(
            start_offset_ms=0,
            duration_ms=self.duration_ms,
            fade_in_ms=self.fade_in_ms,
            fade_out_ms=self.fade_out_ms,
        )


@dataclass(frozen=True, slots=True)
class AvatarPerformanceTrack:
    """他Trackと時間的に重なり、Avatar Runtime内で合成される演技Track。"""

    track_id: str
    channel: AvatarTrackChannel
    start_offset_ms: int
    duration_ms: int
    fade_in_ms: int = 150
    fade_out_ms: int = 250
    blend_mode: AvatarBlendMode = AvatarBlendMode.OVERRIDE
    continuity: AvatarContinuity = AvatarContinuity.CURRENT
    hold: bool = False
    layer_priority: int = 0
    expression: AvatarExpressionIntent | None = None
    attention: AvatarGazeIntent | None = None
    motion: AvatarMotionIntent | None = None
    pose: AvatarPoseIntent | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "track_id", _normalize_name(self.track_id, "track_id"))
        _validate_timing(
            start_offset_ms=self.start_offset_ms,
            duration_ms=self.duration_ms,
            fade_in_ms=self.fade_in_ms,
            fade_out_ms=self.fade_out_ms,
        )
        if not isinstance(self.hold, bool):
            raise TypeError("hold must be a boolean")
        if isinstance(self.layer_priority, bool) or not isinstance(
            self.layer_priority, int
        ):
            raise TypeError("layer_priority must be an integer")
        if not -1000 <= self.layer_priority <= 1000:
            raise ValueError("layer_priority must be between -1000 and 1000")

        payloads = tuple(
            value
            for value in (self.expression, self.attention, self.motion, self.pose)
            if value is not None
        )
        if len(payloads) != 1:
            raise ValueError("track requires exactly one intent payload")
        if self.channel == AvatarTrackChannel.EXPRESSION and self.expression is None:
            raise ValueError("expression track requires expression intent")
        if self.channel == AvatarTrackChannel.ATTENTION and self.attention is None:
            raise ValueError("attention track requires attention intent")
        if self.channel == AvatarTrackChannel.FACE and self.pose is None:
            raise ValueError("face track requires pose intent")
        if self.channel not in {
            AvatarTrackChannel.EXPRESSION,
            AvatarTrackChannel.ATTENTION,
            AvatarTrackChannel.FACE,
        } and self.motion is None and self.pose is None:
            raise ValueError("body track requires motion or pose intent")

    @property
    def end_offset_ms(self) -> int:
        return self.start_offset_ms + self.duration_ms


def _validate_timing(
    *,
    start_offset_ms: int,
    duration_ms: int,
    fade_in_ms: int,
    fade_out_ms: int,
) -> None:
    for field_name, value, minimum, maximum in (
        ("start_offset_ms", start_offset_ms, 0, 120_000),
        ("duration_ms", duration_ms, 100, 120_000),
        ("fade_in_ms", fade_in_ms, 0, 10_000),
        ("fade_out_ms", fade_out_ms, 0, 10_000),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(
                f"{field_name} must be between {minimum} and {maximum}"
            )
    if fade_in_ms > duration_ms:
        raise ValueError("fade_in_ms must not exceed duration_ms")
    if fade_out_ms > duration_ms:
        raise ValueError("fade_out_ms must not exceed duration_ms")


@dataclass(frozen=True, slots=True)
class AvatarPerformancePlan:
    """Avatar Runtimeへ渡すエンジン非依存の複合演技計画。"""

    performance_id: str
    source_activity_id: str
    output_unit_id: str
    priority: int
    segments: tuple[AvatarPerformanceSegment, ...] = ()
    tracks: tuple[AvatarPerformanceTrack, ...] = ()
    interrupt_policy: AvatarInterruptPolicy = (
        AvatarInterruptPolicy.REPLACE_LOWER_PRIORITY
    )
    return_behavior: AvatarReturnBehavior = AvatarReturnBehavior.HOLD

    def __post_init__(self) -> None:
        for field_name in (
            "performance_id",
            "source_activity_id",
            "output_unit_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            if len(value) > 128:
                raise ValueError(f"{field_name} must be 128 characters or fewer")
            object.__setattr__(self, field_name, value)
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not 0 <= self.priority <= 1000:
            raise ValueError("priority must be between 0 and 1000")
        if not self.segments and not self.tracks:
            raise ValueError(
                "AvatarPerformancePlan requires at least one track or segment"
            )
        if len(self.segments) > 8:
            raise ValueError("AvatarPerformancePlan supports at most 8 segments")
        if len(self.tracks) > 64:
            raise ValueError("AvatarPerformancePlan supports at most 64 tracks")

    @property
    def duration_ms(self) -> int:
        if self.tracks:
            return max(track.end_offset_ms for track in self.tracks)
        return sum(segment.duration_ms for segment in self.segments)
