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
    """描画方式に依存しないジェスチャーIntent。"""

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
    """描画方式に依存しない高レベル視線Intent。"""

    target: str
    behavior: str = "maintain"
    intensity: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _normalize_name(self.target, "gaze target"))
        object.__setattr__(
            self,
            "behavior",
            _normalize_name(self.behavior, "gaze behavior"),
        )
        object.__setattr__(
            self,
            "intensity",
            _validate_intensity(self.intensity, "gaze intensity"),
        )


@dataclass(frozen=True, slots=True)
class AvatarPerformanceSegment:
    """同じ表現意図を維持するAvatar Runtime向け演技区間。"""

    expression: AvatarExpressionIntent
    gesture: AvatarGestureIntent | None = None
    gaze: AvatarGazeIntent | None = None
    duration_ms: int = 1000
    fade_in_ms: int = 150
    fade_out_ms: int = 250

    def __post_init__(self) -> None:
        for field_name, value, minimum, maximum in (
            ("duration_ms", self.duration_ms, 100, 30_000),
            ("fade_in_ms", self.fade_in_ms, 0, 5_000),
            ("fade_out_ms", self.fade_out_ms, 0, 5_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{field_name} must be between {minimum} and {maximum}"
                )
        if self.fade_in_ms > self.duration_ms:
            raise ValueError("fade_in_ms must not exceed duration_ms")
        if self.fade_out_ms > self.duration_ms:
            raise ValueError("fade_out_ms must not exceed duration_ms")


@dataclass(frozen=True, slots=True)
class AvatarPerformancePlan:
    """ReactionPlanをAvatar Runtimeへ渡すエンジン非依存の演技計画。"""

    performance_id: str
    source_activity_id: str
    output_unit_id: str
    priority: int
    segments: tuple[AvatarPerformanceSegment, ...]
    interrupt_policy: AvatarInterruptPolicy = (
        AvatarInterruptPolicy.REPLACE_LOWER_PRIORITY
    )
    return_behavior: AvatarReturnBehavior = AvatarReturnBehavior.NEUTRAL

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
        if not self.segments:
            raise ValueError("AvatarPerformancePlan requires at least one segment")
        if len(self.segments) > 8:
            raise ValueError("AvatarPerformancePlan supports at most 8 segments")
