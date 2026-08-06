from __future__ import annotations

from dataclasses import dataclass, fields

from app.domain.body_value_validation import bounded_number, normalized_identifier


@dataclass(frozen=True, slots=True)
class BodyAffectChannels:
    """Emotion StateからBodyへ投影した短期感情チャネル。

    Emotionを更新せず、確定済みReactive EmotionのSnapshotだけを保持する。
    """

    joy: float = 0.0
    amusement: float = 0.0
    anger: float = 0.0
    sadness: float = 0.0
    fear: float = 0.0
    surprise: float = 0.0
    discomfort: float = 0.0
    emotional_pressure: float = 0.0

    def __post_init__(self) -> None:
        for value_field in fields(self):
            object.__setattr__(
                self,
                value_field.name,
                bounded_number(
                    getattr(self, value_field.name),
                    value_field.name,
                    0.0,
                    1.0,
                ),
            )

    def as_payload(self) -> dict[str, float]:
        return {
            value_field.name: getattr(self, value_field.name)
            for value_field in fields(self)
        }


@dataclass(frozen=True, slots=True)
class BodyAffectBaseline:
    """Body表現の感情起点となるモデル非依存な基礎状態。"""

    channels: BodyAffectChannels
    dominant_affect: str
    intensity: float
    valence: float
    arousal: float
    tension: float
    openness: float
    approach: float
    warmth: float
    surprise: float
    assertiveness: float
    expressiveness: float
    avoidance: float

    def __post_init__(self) -> None:
        if not isinstance(self.channels, BodyAffectChannels):
            raise TypeError("channels must be BodyAffectChannels")
        object.__setattr__(
            self,
            "dominant_affect",
            normalized_identifier(self.dominant_affect, "dominant_affect"),
        )
        for field_name in (
            "intensity",
            "arousal",
            "tension",
            "openness",
            "warmth",
            "surprise",
            "assertiveness",
            "expressiveness",
            "avoidance",
        ):
            object.__setattr__(
                self,
                field_name,
                bounded_number(
                    getattr(self, field_name),
                    field_name,
                    0.0,
                    1.0,
                ),
            )
        for field_name in ("valence", "approach"):
            object.__setattr__(
                self,
                field_name,
                bounded_number(
                    getattr(self, field_name),
                    field_name,
                    -1.0,
                    1.0,
                ),
            )

    def as_payload(self) -> dict[str, object]:
        return {
            "channels": self.channels.as_payload(),
            "dominant_affect": self.dominant_affect,
            "intensity": self.intensity,
            "valence": self.valence,
            "arousal": self.arousal,
            "tension": self.tension,
            "openness": self.openness,
            "approach": self.approach,
            "warmth": self.warmth,
            "surprise": self.surprise,
            "assertiveness": self.assertiveness,
            "expressiveness": self.expressiveness,
            "avoidance": self.avoidance,
        }


@dataclass(frozen=True, slots=True)
class BodyFacialAffectTarget:
    """顔の部品名・BlendShape名に依存しない感情表現ターゲット。"""

    smile: float = 0.0
    frown: float = 0.0
    brow_raise: float = 0.0
    brow_tension: float = 0.0
    eye_widen: float = 0.0
    eye_narrow: float = 0.0
    mouth_tension: float = 0.0

    def __post_init__(self) -> None:
        for value_field in fields(self):
            object.__setattr__(
                self,
                value_field.name,
                bounded_number(
                    getattr(self, value_field.name),
                    value_field.name,
                    0.0,
                    1.0,
                ),
            )

    def as_payload(self) -> dict[str, float]:
        return {
            value_field.name: getattr(self, value_field.name)
            for value_field in fields(self)
        }
