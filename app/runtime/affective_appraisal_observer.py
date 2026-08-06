from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.domain.emotions import (
    AffectiveAppraisal,
    AffectiveAppraisalComparison,
    AffectiveAppraisalDimensions,
    AffectiveEmotionProjection,
    AffectiveInputMeaning,
    EmotionAppraisal,
    EmotionState,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.relationships import RelationshipState
from app.runtime.emotion_state_updater import EmotionStateUpdater
from app.shared.contracts.memory import EmotionHistoryRecord
from app.utils.trace import TraceLogger


class AffectiveAppraisalObserver:
    """現行Emotion更新を変更せず、心理的評価の証拠と投影差分を観測する。"""

    _SOCIAL_EVENT_TYPES = {
        AgentEventType.USER_TEXT,
        AgentEventType.USER_SPEECH,
        AgentEventType.YOUTUBE_COMMENT,
        AgentEventType.USER_INTERACTION,
    }

    def __init__(
        self,
        *,
        emotion_state_updater: EmotionStateUpdater | None = None,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._emotion_state_updater = emotion_state_updater or EmotionStateUpdater()
        self._trace_logger = trace_logger or TraceLogger()

    def observe(
        self,
        event: AgentEvent,
        *,
        legacy_appraisal: EmotionAppraisal,
        before_emotion: EmotionState,
        actual_after_emotion: EmotionState,
        relationship: RelationshipState | None,
        recent_history: Sequence[EmotionHistoryRecord] = (),
    ) -> tuple[AffectiveAppraisal, AffectiveAppraisalComparison]:
        meaning = self._extract_meaning(event.payload)
        projected_after = self._emotion_state_updater.apply(
            before_emotion,
            legacy_appraisal,
        )
        cause_category = (
            legacy_appraisal.cause.category
            if legacy_appraisal.cause is not None
            else legacy_appraisal.reason
        )
        dimensions = self._dimensions(
            event,
            meaning=meaning,
            projected_after=projected_after,
            relationship=relationship,
            appraisal_confidence=legacy_appraisal.confidence,
        )
        appraisal = AffectiveAppraisal(
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            meaning=meaning,
            dimensions=dimensions,
            emotion_projection=AffectiveEmotionProjection.from_emotion_appraisal(
                legacy_appraisal
            ),
            projection_source="legacy_emotion_appraiser_shadow",
            cause_category=cause_category or "no_change",
            confidence=(
                meaning.confidence
                if meaning.confidence is not None
                else legacy_appraisal.confidence
            ),
            relationship_counterpart_id=(
                relationship.counterpart_id if relationship is not None else None
            ),
            relationship_role=(relationship.role if relationship is not None else None),
            recent_emotion_history_count=len(recent_history),
            similar_cause_count=sum(
                1
                for item in recent_history
                if item.cause_category == cause_category or item.reason == cause_category
            ),
        )
        comparison = AffectiveAppraisalComparison.compare(
            projected_after,
            actual_after_emotion,
        )
        self._trace_logger.info(
            "affective_appraisal:shadow_compared",
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            projection_source=appraisal.projection_source,
            cause_category=appraisal.cause_category,
            appraisal_confidence=appraisal.confidence,
            meaning_available=meaning.available,
            meaning_source=meaning.source,
            input_speech_act=meaning.input_speech_act,
            primary_intent=meaning.primary_intent,
            expected_response=meaning.expected_response,
            target_type=meaning.target_type,
            target_id=meaning.target_id,
            relationship_available=relationship is not None,
            relationship_counterpart_id=appraisal.relationship_counterpart_id,
            recent_emotion_history_count=appraisal.recent_emotion_history_count,
            similar_cause_count=appraisal.similar_cause_count,
            dimensions=dimensions.as_context(),
            comparison_matched=comparison.matched,
            comparison_max_abs_difference=comparison.max_abs_difference,
            comparison_mismatched_fields=list(comparison.mismatched_fields),
        )
        return appraisal, comparison

    def _dimensions(
        self,
        event: AgentEvent,
        *,
        meaning: AffectiveInputMeaning,
        projected_after: EmotionState,
        relationship: RelationshipState | None,
        appraisal_confidence: float,
    ) -> AffectiveAppraisalDimensions:
        reactive = projected_after.reactive
        relationship_significance = 0.0
        if relationship is not None:
            normalized_affinity = (relationship.affinity + 1.0) / 2.0
            relationship_significance = self._clamp(
                relationship.familiarity * 0.30
                + relationship.trust * 0.35
                + normalized_affinity * 0.35,
                0.0,
                1.0,
            )
        social_relevance = self._social_relevance(event, relationship)
        tension = max(
            reactive.anger,
            reactive.fear,
            reactive.discomfort,
            reactive.emotional_pressure,
        )
        approach = self._clamp(
            projected_after.valence
            + reactive.joy * 0.35
            + reactive.amusement * 0.20
            - reactive.fear * 0.45
            - reactive.discomfort * 0.45
            - reactive.anger * 0.20,
            -1.0,
            1.0,
        )
        return AffectiveAppraisalDimensions(
            pleasantness=projected_after.valence,
            activation=projected_after.arousal,
            novelty=reactive.surprise,
            social_relevance=social_relevance,
            relationship_significance=relationship_significance,
            certainty=(
                meaning.confidence
                if meaning.confidence is not None
                else appraisal_confidence
            ),
            controllability=self._controllability(event.event_type),
            approach=approach,
            tension=tension,
        )

    @classmethod
    def _extract_meaning(
        cls,
        payload: Mapping[str, object],
    ) -> AffectiveInputMeaning:
        candidates: tuple[tuple[str, object], ...] = (
            ("payload.structured_input_meaning", payload.get("structured_input_meaning")),
            ("payload.input_meaning", payload.get("input_meaning")),
            (
                "payload._internal_directive.structured_input_meaning",
                cls._nested(payload.get("_internal_directive"), "structured_input_meaning"),
            ),
            (
                "payload.validated_action_plan.structured_input_meaning",
                cls._nested(payload.get("validated_action_plan"), "structured_input_meaning"),
            ),
        )
        for source, candidate in candidates:
            mapping = cls._as_mapping(candidate)
            if mapping is not None:
                target_value = mapping.get("target")
                target = target_value if isinstance(target_value, Mapping) else {}
                confidence = cls._optional_number(mapping.get("confidence"))
                return AffectiveInputMeaning(
                    available=True,
                    source=source,
                    input_speech_act=cls._optional_text(
                        mapping.get("input_speech_act")
                    ),
                    primary_intent=cls._optional_text(mapping.get("primary_intent")),
                    expected_response=cls._optional_text(
                        mapping.get("expected_response")
                    ),
                    target_type=cls._optional_text(
                        target.get("type") or target.get("target_type")
                    ),
                    target_id=cls._optional_text(
                        target.get("id") or target.get("target_id")
                    ),
                    confidence=confidence,
                )
        return AffectiveInputMeaning()

    @staticmethod
    def _as_mapping(value: object) -> Mapping[str, object] | None:
        if isinstance(value, Mapping):
            return value
        as_context = getattr(value, "as_context", None)
        if callable(as_context):
            context = as_context()
            if isinstance(context, Mapping):
                return context
        return None

    @staticmethod
    def _nested(value: object, key: str) -> object:
        return value.get(key) if isinstance(value, Mapping) else None

    @classmethod
    def _social_relevance(
        cls,
        event: AgentEvent,
        relationship: RelationshipState | None,
    ) -> float:
        if event.event_type in cls._SOCIAL_EVENT_TYPES:
            return 1.0 if relationship is not None else 0.75
        if event.event_type in {
            AgentEventType.SPEECH_STARTED,
            AgentEventType.SPEECH_FINISHED,
        }:
            return 0.60
        if event.event_type in {
            AgentEventType.STREAM_STARTED,
            AgentEventType.STREAM_ENDED,
        }:
            return 0.50
        if event.event_type == AgentEventType.ACTION_FAILED:
            return 0.35
        return 0.20

    @staticmethod
    def _controllability(event_type: AgentEventType) -> float:
        if event_type == AgentEventType.ACTION_FAILED:
            return 0.20
        if event_type == AgentEventType.USER_INTERACTION:
            return 0.40
        if event_type in {
            AgentEventType.USER_TEXT,
            AgentEventType.USER_SPEECH,
            AgentEventType.YOUTUBE_COMMENT,
        }:
            return 0.55
        if event_type in {
            AgentEventType.STREAM_STARTED,
            AgentEventType.STREAM_ENDED,
        }:
            return 0.70
        return 0.50

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _optional_number(value: object) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
        return None

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
