from __future__ import annotations

from dataclasses import dataclass

from .emotion_appraisal import EmotionAppraisal
from .emotion_state import EmotionState


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class AffectiveInputMeaning:
    """Affective Appraisalが参照した入力意味の安全な要約。"""

    available: bool = False
    source: str = "unavailable"
    input_speech_act: str | None = None
    primary_intent: str | None = None
    expected_response: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        source = self.source.strip() or "unavailable"
        object.__setattr__(self, "source", source)
        for field_name in (
            "input_speech_act",
            "primary_intent",
            "expected_response",
            "target_type",
            "target_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name)),
            )
        if self.confidence is not None:
            object.__setattr__(self, "confidence", _clamp(self.confidence, 0.0, 1.0))

    def as_context(self) -> dict[str, object]:
        return {
            "available": self.available,
            "source": self.source,
            "input_speech_act": self.input_speech_act,
            "primary_intent": self.primary_intent,
            "expected_response": self.expected_response,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class AffectiveAppraisalDimensions:
    """出来事をどう受け止めたかを表す、出力非依存の観測軸。"""

    pleasantness: float = 0.0
    activation: float = 0.5
    novelty: float = 0.0
    social_relevance: float = 0.0
    relationship_significance: float = 0.0
    certainty: float = 0.5
    controllability: float = 0.5
    approach: float = 0.0
    tension: float = 0.0

    def __post_init__(self) -> None:
        for field_name in ("pleasantness", "approach"):
            object.__setattr__(
                self,
                field_name,
                _clamp(getattr(self, field_name), -1.0, 1.0),
            )
        for field_name in (
            "activation",
            "novelty",
            "social_relevance",
            "relationship_significance",
            "certainty",
            "controllability",
            "tension",
        ):
            object.__setattr__(
                self,
                field_name,
                _clamp(getattr(self, field_name), 0.0, 1.0),
            )

    def as_context(self) -> dict[str, float]:
        return {
            "pleasantness": self.pleasantness,
            "activation": self.activation,
            "novelty": self.novelty,
            "social_relevance": self.social_relevance,
            "relationship_significance": self.relationship_significance,
            "certainty": self.certainty,
            "controllability": self.controllability,
            "approach": self.approach,
            "tension": self.tension,
        }


@dataclass(frozen=True, slots=True)
class AffectiveEmotionProjection:
    """Affective AppraisalからEmotion Stateへ投影する差分。"""

    joy_delta: float = 0.0
    amusement_delta: float = 0.0
    anger_delta: float = 0.0
    sadness_delta: float = 0.0
    fear_delta: float = 0.0
    surprise_delta: float = 0.0
    discomfort_delta: float = 0.0
    pressure_delta: float = 0.0
    arousal_delta: float = 0.0
    valence_delta: float = 0.0
    talkativeness_delta: float = 0.0

    @classmethod
    def from_emotion_appraisal(
        cls,
        appraisal: EmotionAppraisal,
    ) -> AffectiveEmotionProjection:
        return cls(
            joy_delta=appraisal.joy_delta,
            amusement_delta=appraisal.amusement_delta,
            anger_delta=appraisal.anger_delta,
            sadness_delta=appraisal.sadness_delta,
            fear_delta=appraisal.fear_delta,
            surprise_delta=appraisal.surprise_delta,
            discomfort_delta=appraisal.discomfort_delta,
            pressure_delta=appraisal.pressure_delta,
            arousal_delta=appraisal.arousal_delta,
            valence_delta=appraisal.valence_delta,
            talkativeness_delta=appraisal.talkativeness_delta,
        )

    def as_context(self) -> dict[str, float]:
        return {
            "joy_delta": self.joy_delta,
            "amusement_delta": self.amusement_delta,
            "anger_delta": self.anger_delta,
            "sadness_delta": self.sadness_delta,
            "fear_delta": self.fear_delta,
            "surprise_delta": self.surprise_delta,
            "discomfort_delta": self.discomfort_delta,
            "pressure_delta": self.pressure_delta,
            "arousal_delta": self.arousal_delta,
            "valence_delta": self.valence_delta,
            "talkativeness_delta": self.talkativeness_delta,
        }


@dataclass(frozen=True, slots=True)
class EmotionStateSnapshot:
    mood: str
    arousal: float
    valence: float
    talkativeness: float
    joy: float
    amusement: float
    anger: float
    sadness: float
    fear: float
    surprise: float
    discomfort: float
    emotional_pressure: float

    @classmethod
    def from_state(cls, state: EmotionState) -> EmotionStateSnapshot:
        return cls(
            mood=state.mood.value,
            arousal=state.arousal,
            valence=state.valence,
            talkativeness=state.talkativeness,
            joy=state.reactive.joy,
            amusement=state.reactive.amusement,
            anger=state.reactive.anger,
            sadness=state.reactive.sadness,
            fear=state.reactive.fear,
            surprise=state.reactive.surprise,
            discomfort=state.reactive.discomfort,
            emotional_pressure=state.reactive.emotional_pressure,
        )

    def numeric_values(self) -> dict[str, float]:
        return {
            "arousal": self.arousal,
            "valence": self.valence,
            "talkativeness": self.talkativeness,
            "joy": self.joy,
            "amusement": self.amusement,
            "anger": self.anger,
            "sadness": self.sadness,
            "fear": self.fear,
            "surprise": self.surprise,
            "discomfort": self.discomfort,
            "emotional_pressure": self.emotional_pressure,
        }

    def as_context(self) -> dict[str, object]:
        return {"mood": self.mood, **self.numeric_values()}


@dataclass(frozen=True, slots=True)
class AffectiveAppraisalComparison:
    """Shadow投影と現行Emotion更新の差分。"""

    matched: bool
    max_abs_difference: float
    mismatched_fields: tuple[str, ...]
    projected: EmotionStateSnapshot
    actual: EmotionStateSnapshot

    @classmethod
    def compare(
        cls,
        projected: EmotionState,
        actual: EmotionState,
        *,
        tolerance: float = 1e-9,
    ) -> AffectiveAppraisalComparison:
        projected_snapshot = EmotionStateSnapshot.from_state(projected)
        actual_snapshot = EmotionStateSnapshot.from_state(actual)
        differences = {
            field_name: abs(
                projected_snapshot.numeric_values()[field_name]
                - actual_snapshot.numeric_values()[field_name]
            )
            for field_name in projected_snapshot.numeric_values()
        }
        mismatched = tuple(
            field_name
            for field_name, difference in differences.items()
            if difference > tolerance
        )
        if projected_snapshot.mood != actual_snapshot.mood:
            mismatched = (*mismatched, "mood")
        return cls(
            matched=not mismatched,
            max_abs_difference=max(differences.values(), default=0.0),
            mismatched_fields=mismatched,
            projected=projected_snapshot,
            actual=actual_snapshot,
        )

    def as_context(self) -> dict[str, object]:
        return {
            "matched": self.matched,
            "max_abs_difference": self.max_abs_difference,
            "mismatched_fields": list(self.mismatched_fields),
            "projected": self.projected.as_context(),
            "actual": self.actual.as_context(),
        }


@dataclass(frozen=True, slots=True)
class AffectiveAppraisal:
    """人格的行動の起点となる感情評価を、Phase 1では観測専用で保持する。"""

    source_event_id: str
    event_type: str
    meaning: AffectiveInputMeaning
    dimensions: AffectiveAppraisalDimensions
    emotion_projection: AffectiveEmotionProjection
    projection_source: str
    cause_category: str
    confidence: float
    relationship_counterpart_id: str | None = None
    relationship_role: str | None = None
    recent_emotion_history_count: int = 0
    similar_cause_count: int = 0

    def __post_init__(self) -> None:
        if not self.source_event_id.strip():
            raise ValueError("source_event_id は空にできません。")
        if not self.event_type.strip():
            raise ValueError("event_type は空にできません。")
        if not self.projection_source.strip():
            raise ValueError("projection_source は空にできません。")
        if not self.cause_category.strip():
            raise ValueError("cause_category は空にできません。")
        if self.recent_emotion_history_count < 0 or self.similar_cause_count < 0:
            raise ValueError("履歴件数は0以上で指定してください。")
        object.__setattr__(self, "confidence", _clamp(self.confidence, 0.0, 1.0))
        object.__setattr__(
            self,
            "relationship_counterpart_id",
            _optional_text(self.relationship_counterpart_id),
        )
        object.__setattr__(
            self,
            "relationship_role",
            _optional_text(self.relationship_role),
        )

    def as_context(self) -> dict[str, object]:
        return {
            "source_event_id": self.source_event_id,
            "event_type": self.event_type,
            "meaning": self.meaning.as_context(),
            "dimensions": self.dimensions.as_context(),
            "emotion_projection": self.emotion_projection.as_context(),
            "projection_source": self.projection_source,
            "cause_category": self.cause_category,
            "confidence": self.confidence,
            "relationship_counterpart_id": self.relationship_counterpart_id,
            "relationship_role": self.relationship_role,
            "recent_emotion_history_count": self.recent_emotion_history_count,
            "similar_cause_count": self.similar_cause_count,
            "observation_only": True,
        }
