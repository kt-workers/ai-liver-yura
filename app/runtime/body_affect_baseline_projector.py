from __future__ import annotations

from app.domain.body_affect import BodyAffectBaseline, BodyAffectChannels
from app.domain.body_value_validation import finite_number
from app.domain.emotions.emotion_state import EmotionState


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


class BodyAffectBaselineProjector:
    """確定済みEmotion StateをBodyの基礎表現軸へ射影する。

    Emotionの更新、Activity選択、Pose生成は行わない。
    """

    def project(self, emotion: EmotionState) -> BodyAffectBaseline:
        if not isinstance(emotion, EmotionState):
            raise TypeError("emotion must be EmotionState")

        reactive = emotion.reactive
        channels = BodyAffectChannels(
            joy=finite_number(reactive.joy, "joy"),
            amusement=finite_number(reactive.amusement, "amusement"),
            anger=finite_number(reactive.anger, "anger"),
            sadness=finite_number(reactive.sadness, "sadness"),
            fear=finite_number(reactive.fear, "fear"),
            surprise=finite_number(reactive.surprise, "surprise"),
            discomfort=finite_number(reactive.discomfort, "discomfort"),
            emotional_pressure=finite_number(
                reactive.emotional_pressure,
                "emotional_pressure",
            ),
        )
        state_valence = finite_number(emotion.valence, "valence")
        state_arousal = finite_number(emotion.arousal, "arousal")
        talkativeness = finite_number(emotion.talkativeness, "talkativeness")

        positive = max(channels.joy, channels.amusement)
        threat = max(
            channels.fear,
            channels.discomfort,
            channels.emotional_pressure,
        )
        reactive_activation = max(
            channels.amusement,
            channels.anger,
            channels.fear,
            channels.surprise,
            channels.emotional_pressure,
        )
        reactive_valence = _clamp(
            (channels.joy + channels.amusement) * 0.5
            - max(
                channels.sadness,
                channels.fear,
                channels.discomfort,
                channels.anger * 0.8,
            ),
            -1.0,
            1.0,
        )
        valence = _clamp(
            state_valence * 0.70 + reactive_valence * 0.30,
            -1.0,
            1.0,
        )
        arousal = _clamp(state_arousal * 0.70 + reactive_activation * 0.30)
        intensity = _clamp(
            max(
                *channels.as_payload().values(),
                abs(valence) * 0.55,
            )
        )
        tension = _clamp(
            max(
                channels.anger,
                channels.fear,
                channels.discomfort,
                channels.emotional_pressure,
            )
            * 0.85
            + channels.surprise * 0.10
        )
        openness = _clamp(
            0.50
            + positive * 0.35
            - threat * 0.45
            - channels.anger * 0.12
        )
        approach = _clamp(
            positive * 0.45
            + channels.anger * 0.18
            - channels.fear * 0.55
            - channels.discomfort * 0.35
            - channels.emotional_pressure * 0.20,
            -1.0,
            1.0,
        )
        warmth = _clamp(
            0.50
            + channels.joy * 0.30
            + channels.amusement * 0.25
            - channels.anger * 0.45
            - channels.discomfort * 0.25
            - channels.emotional_pressure * 0.15
        )
        assertiveness = _clamp(
            channels.anger * 0.62
            + positive * 0.12
            + arousal * 0.16
            - channels.emotional_pressure * 0.10
        )
        expressiveness = _clamp(
            talkativeness * 0.55 + intensity * 0.30 + arousal * 0.15
        )
        avoidance = _clamp(
            max(
                channels.fear,
                channels.discomfort * 0.90,
                channels.emotional_pressure * 0.80,
            )
        )

        values = channels.as_payload()
        dominant_name, dominant_value = max(values.items(), key=lambda item: item[1])
        dominant_affect = (
            emotion.mood.value if dominant_value <= 0.05 else dominant_name
        )

        return BodyAffectBaseline(
            channels=channels,
            dominant_affect=dominant_affect,
            intensity=intensity,
            valence=valence,
            arousal=arousal,
            tension=tension,
            openness=openness,
            approach=approach,
            warmth=warmth,
            surprise=channels.surprise,
            assertiveness=assertiveness,
            expressiveness=expressiveness,
            avoidance=avoidance,
        )
