from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class BodyAttentionBehavior(str, Enum):
    """Bodyが注意対象をどのように扱うかを表す。"""

    MAINTAIN = "maintain"
    GLANCE = "glance"
    AVOID = "avoid"
    SEARCH = "search"
    WANDER = "wander"


class BodyPostureTendency(str, Enum):
    """Activity中に維持する姿勢傾向。"""

    NEUTRAL = "neutral"
    OPEN = "open"
    CLOSED = "closed"
    FORWARD = "forward"
    WITHDRAWN = "withdrawn"


def _normalize_name(value: str, field_name: str, *, maximum: int = 80) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer")
    return normalized


def _unit(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    return normalized


def _signed_unit(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    normalized = float(value)
    if not -1.0 <= normalized <= 1.0:
        raise ValueError(f"{field_name} must be between -1.0 and 1.0")
    return normalized


@dataclass(frozen=True, slots=True)
class EmbodiedExpressionIntent:
    """身体部位やモーション名に依存しない演技意図。

    Character LLMや内部状態は「どう感じ、どう表したいか」までを指定する。
    首・胴体・腕へどう展開するかはBody Subsystemが決定する。
    """

    attitude: str = "neutral"
    intensity: float = 0.0
    valence: float = 0.0
    arousal: float = 0.0
    tension: float = 0.0
    openness: float = 0.5
    approach: float = 0.0
    agreement: float = 0.0
    surprise: float = 0.0
    assertiveness: float = 0.0
    warmth: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attitude",
            _normalize_name(self.attitude, "embodied expression attitude"),
        )
        for field_name in (
            "intensity",
            "arousal",
            "tension",
            "openness",
            "surprise",
            "assertiveness",
            "warmth",
        ):
            object.__setattr__(
                self,
                field_name,
                _unit(getattr(self, field_name), field_name),
            )
        for field_name in ("valence", "approach", "agreement"):
            object.__setattr__(
                self,
                field_name,
                _signed_unit(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class BodyAttentionIntent:
    """Bodyが意味上の対象へ向ける注意の方針。"""

    target: str
    behavior: BodyAttentionBehavior = BodyAttentionBehavior.MAINTAIN
    engagement: float = 1.0
    avoidance: float = 0.0
    eye_follow: float = 1.0
    head_follow: float = 0.55
    body_follow: float = 0.15

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target",
            _normalize_name(self.target, "body attention target"),
        )
        for field_name in (
            "engagement",
            "avoidance",
            "eye_follow",
            "head_follow",
            "body_follow",
        ):
            object.__setattr__(
                self,
                field_name,
                _unit(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class SpeechEmphasis:
    """発話内の意味的な強調点。実時間への変換は音声生成後に行う。"""

    text: str
    intent: str
    strength: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _normalize_name(self.text, "emphasis text"))
        object.__setattr__(
            self,
            "intent",
            _normalize_name(self.intent, "emphasis intent"),
        )
        object.__setattr__(
            self,
            "strength",
            _unit(self.strength, "emphasis strength"),
        )


@dataclass(frozen=True, slots=True)
class BodyActivityContext:
    """ActivityがBodyへ継続的に提示する身体文脈。

    毎フレームの角度やポーズではなく、注意対象・姿勢傾向・動きの自由度を表す。
    """

    source_activity_id: str
    attention_target: str | None = None
    engagement: float = 0.5
    posture_tendency: BodyPostureTendency = BodyPostureTendency.NEUTRAL
    movement_energy: float = 0.35
    gaze_freedom: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_activity_id",
            _normalize_name(
                self.source_activity_id,
                "source_activity_id",
                maximum=128,
            ),
        )
        if self.attention_target is not None:
            object.__setattr__(
                self,
                "attention_target",
                _normalize_name(self.attention_target, "attention_target"),
            )
        for field_name in ("engagement", "movement_energy", "gaze_freedom"):
            object.__setattr__(
                self,
                field_name,
                _unit(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class BodyExpressionRequest:
    """脳側からBodyへ必要時だけ送る高レベルな表現要求。"""

    source_activity_id: str
    output_unit_id: str
    expression: EmbodiedExpressionIntent
    attention: BodyAttentionIntent | None = None
    facial_expression: str | None = None
    facial_intensity: float = 1.0
    speech_emphasis: tuple[SpeechEmphasis, ...] = ()
    priority: int = 0
    duration_hint_ms: int | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        for field_name in ("source_activity_id", "output_unit_id", "request_id"):
            object.__setattr__(
                self,
                field_name,
                _normalize_name(
                    str(getattr(self, field_name)),
                    field_name,
                    maximum=128,
                ),
            )
        if self.facial_expression is not None:
            object.__setattr__(
                self,
                "facial_expression",
                _normalize_name(self.facial_expression, "facial_expression"),
            )
        object.__setattr__(
            self,
            "facial_intensity",
            _unit(self.facial_intensity, "facial_intensity"),
        )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not 0 <= self.priority <= 1000:
            raise ValueError("priority must be between 0 and 1000")
        object.__setattr__(self, "speech_emphasis", tuple(self.speech_emphasis))
        if len(self.speech_emphasis) > 16:
            raise ValueError("speech_emphasis supports at most 16 entries")
        if self.duration_hint_ms is not None:
            if isinstance(self.duration_hint_ms, bool) or not isinstance(
                self.duration_hint_ms,
                int,
            ):
                raise TypeError("duration_hint_ms must be an integer")
            if not 100 <= self.duration_hint_ms <= 120_000:
                raise ValueError(
                    "duration_hint_ms must be between 100 and 120000"
                )


@dataclass(frozen=True, slots=True)
class SpeechPresentationRequest:
    """生成済み音声を口・表情・身体と同期して提示するための契約。

    audio_referenceはファイル、共有バッファ、ストリームIDなどTransport依存の参照値。
    Body SubsystemはTTS生成を担当せず、再生時計と身体同期を担当する。
    """

    source_activity_id: str
    output_unit_id: str
    text: str
    audio_reference: str
    duration_ms: int
    emphasis: tuple[SpeechEmphasis, ...] = ()
    presentation_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        for field_name, maximum in (
            ("source_activity_id", 128),
            ("output_unit_id", 128),
            ("audio_reference", 512),
            ("presentation_id", 128),
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_name(
                    str(getattr(self, field_name)),
                    field_name,
                    maximum=maximum,
                ),
            )
        object.__setattr__(
            self,
            "text",
            _normalize_name(self.text, "text", maximum=4000),
        )
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int):
            raise TypeError("duration_ms must be an integer")
        if not 100 <= self.duration_ms <= 600_000:
            raise ValueError("duration_ms must be between 100 and 600000")
        object.__setattr__(self, "emphasis", tuple(self.emphasis))
        if len(self.emphasis) > 16:
            raise ValueError("emphasis supports at most 16 entries")
