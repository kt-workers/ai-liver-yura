from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

from app.domain.desires import DesireState, DesireType, DesireValue
from app.domain.emotions import AffectiveAppraisal, EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_desire_satisfaction_evaluator import (
    ActivityDesireSatisfactionEvaluator,
)
from app.utils.trace import TraceLogger


DesireDelta = tuple[float, float, float]


class DesireStateUpdater:
    """Emotion由来の方向とActivity結果からDesireStateを更新する。"""

    _USER_INPUT_DELTAS: Mapping[DesireType, DesireDelta] = {
        DesireType.CONNECTION: (0.06, 0.0, 0.0),
        DesireType.CURIOSITY: (0.04, 0.0, 0.0),
        DesireType.EXPRESSION: (0.02, 0.0, 0.0),
        DesireType.RECOGNITION: (0.01, 0.0, 0.0),
    }

    _OUTCOME_DELTAS: Mapping[
        AgentEventType,
        Mapping[DesireType, DesireDelta],
    ] = {
        AgentEventType.SPEECH_FINISHED: {
            DesireType.CONNECTION: (0.0, 0.02, 0.0),
            DesireType.EXPRESSION: (0.0, 0.10, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.02, 0.0),
        },
        AgentEventType.STREAM_COMMENT_RESPONSE: {
            DesireType.CONNECTION: (0.0, 0.04, 0.0),
            DesireType.RECOGNITION: (0.0, 0.03, 0.0),
        },
        AgentEventType.STREAM_ENDED: {
            DesireType.EXPRESSION: (0.0, 0.04, 0.0),
            DesireType.RECOGNITION: (0.0, 0.06, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.10, 0.0),
        },
    }

    def __init__(
        self,
        *,
        activity_result_evaluator: ActivityDesireSatisfactionEvaluator | None = None,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._activity_result_evaluator = (
            activity_result_evaluator or ActivityDesireSatisfactionEvaluator()
        )
        self._trace_logger = trace_logger or TraceLogger()

    def update_from_affect(
        self,
        desire: DesireState,
        event: AgentEvent,
        *,
        affective_appraisal: AffectiveAppraisal,
        before_emotion: EmotionState,
        after_emotion: EmotionState,
    ) -> DesireState:
        """Emotion変化を欲望の方向へ変換し、結果による充足を重ねる。"""

        if event.event_type == AgentEventType.ACTIVITY_RESULT_RECORDED:
            updated = self._apply_deltas(
                desire,
                self._activity_result_evaluator.evaluate(event),
            )
            self._write_causal_trace(
                event,
                desire,
                updated,
                affective_appraisal=affective_appraisal,
                update_source="activity_result_appraisal",
            )
            return updated

        affect_deltas = self._affect_deltas(
            affective_appraisal,
            before_emotion=before_emotion,
            after_emotion=after_emotion,
        )
        updated = self._apply_deltas(desire, affect_deltas)
        outcome_deltas = self._OUTCOME_DELTAS.get(event.event_type)
        if outcome_deltas is not None:
            updated = self._apply_deltas(updated, outcome_deltas)

        self._write_causal_trace(
            event,
            desire,
            updated,
            affective_appraisal=affective_appraisal,
            update_source=(
                "affect_plus_outcome"
                if outcome_deltas is not None
                else "affective_appraisal"
            ),
        )
        return updated

    def update_by_event(
        self,
        desire: DesireState,
        event: AgentEvent,
    ) -> DesireState:
        """旧Event直接更新。移行期間の互換APIとしてのみ維持する。"""

        if event.event_type == AgentEventType.ACTIVITY_RESULT_RECORDED:
            return self._apply_deltas(
                desire,
                self._activity_result_evaluator.evaluate(event),
            )

        if event.event_type in {
            AgentEventType.USER_TEXT,
            AgentEventType.YOUTUBE_COMMENT,
            AgentEventType.USER_SPEECH,
        }:
            return self._apply_deltas(desire, self._USER_INPUT_DELTAS)

        deltas_by_event: dict[
            AgentEventType,
            Mapping[DesireType, DesireDelta],
        ] = {
            AgentEventType.USER_INTERACTION: {
                DesireType.CONNECTION: (0.025, 0.0, 0.0),
                DesireType.CURIOSITY: (0.02, 0.0, 0.0),
            },
            AgentEventType.SILENCE_TIMEOUT: {
                DesireType.CONNECTION: (0.03, 0.0, 0.015),
                DesireType.EXPRESSION: (0.03, 0.0, 0.015),
            },
            AgentEventType.TREND_UPDATED: {
                DesireType.CURIOSITY: (0.08, 0.0, 0.0),
            },
            AgentEventType.STREAM_STARTED: {
                DesireType.EXPRESSION: (0.06, 0.0, 0.0),
                DesireType.RECOGNITION: (0.05, 0.0, 0.0),
                DesireType.ACHIEVEMENT: (0.05, 0.0, 0.0),
            },
            **self._OUTCOME_DELTAS,
            AgentEventType.ACTION_FAILED: {
                DesireType.SECURITY: (0.04, 0.0, 0.0),
                DesireType.ACHIEVEMENT: (0.05, 0.0, 0.08),
            },
        }
        deltas = deltas_by_event.get(event.event_type)
        if deltas is None:
            return desire
        return self._apply_deltas(desire, deltas)

    def update_by_elapsed_time(
        self,
        desire: DesireState,
        *,
        elapsed_seconds: float,
    ) -> DesireState:
        """欲望をbaselineへ戻し、充足と不満を時間変化させる。"""

        elapsed_minutes = max(0.0, elapsed_seconds) / 60.0
        if elapsed_minutes == 0.0:
            return desire

        updated = desire
        for desire_type in DesireType:
            value = updated.get(desire_type)
            updated = updated.with_value(
                desire_type,
                self._update_value_by_elapsed_time(value, elapsed_minutes),
            )
        return updated

    def update_by_timestamps(
        self,
        desire: DesireState,
        *,
        previous_time: datetime,
        current_time: datetime,
    ) -> DesireState:
        elapsed_seconds = (current_time - previous_time).total_seconds()
        return self.update_by_elapsed_time(
            desire,
            elapsed_seconds=elapsed_seconds,
        )

    @classmethod
    def _affect_deltas(
        cls,
        appraisal: AffectiveAppraisal,
        *,
        before_emotion: EmotionState,
        after_emotion: EmotionState,
    ) -> Mapping[DesireType, DesireDelta]:
        projection = appraisal.emotion_projection
        dimensions = appraisal.dimensions
        positive_activation = max(0.0, after_emotion.arousal - before_emotion.arousal)
        positive_talk = max(
            0.0,
            after_emotion.talkativeness - before_emotion.talkativeness,
        )
        negative_valence = max(0.0, -projection.valence_delta)
        cause = appraisal.cause_category.lower()

        social_emotion = (
            max(0.0, projection.joy_delta) * 0.16
            + max(0.0, projection.sadness_delta) * 0.18
            + positive_talk * 0.22
        ) * dimensions.social_relevance
        curiosity = (
            dimensions.novelty * 0.06
            + max(0.0, projection.surprise_delta) * 0.22
            + positive_activation * 0.08
        )
        expression = (
            positive_activation * 0.14
            + abs(projection.valence_delta) * 0.10
            + max(0.0, projection.pressure_delta) * 0.06
            + positive_talk * 0.18
        )
        security = (
            max(0.0, projection.fear_delta) * 0.28
            + max(0.0, projection.discomfort_delta) * 0.24
            + max(0.0, projection.pressure_delta) * 0.18
            + negative_valence * 0.08
        )
        autonomy = (
            max(0.0, projection.anger_delta) * 0.10
            + max(0.0, projection.pressure_delta) * 0.04
        )
        recognition = max(0.0, projection.joy_delta) * (
            0.10 if any(token in cause for token in ("praise", "recogn", "attention")) else 0.03
        )
        achievement_level = (
            max(0.0, projection.anger_delta) * 0.06
            + max(0.0, projection.discomfort_delta) * 0.05
        )
        achievement_frustration = (
            0.08 * dimensions.tension
            if any(token in cause for token in ("failed", "failure"))
            else 0.0
        )

        deltas: dict[DesireType, DesireDelta] = {
            DesireType.CONNECTION: (social_emotion, 0.0, 0.0),
            DesireType.CURIOSITY: (curiosity, 0.0, 0.0),
            DesireType.EXPRESSION: (expression, 0.0, 0.0),
            DesireType.RECOGNITION: (recognition, 0.0, 0.0),
            DesireType.AUTONOMY: (autonomy, 0.0, 0.0),
            DesireType.SECURITY: (security, 0.0, 0.0),
            DesireType.ACHIEVEMENT: (
                achievement_level,
                0.0,
                achievement_frustration,
            ),
        }
        return {
            desire_type: delta
            for desire_type, delta in deltas.items()
            if any(abs(value) > 1e-12 for value in delta)
        }

    @staticmethod
    def _apply_deltas(
        desire: DesireState,
        deltas: Mapping[DesireType, DesireDelta],
    ) -> DesireState:
        updated = desire
        for desire_type, delta in deltas.items():
            level_delta, satisfaction_delta, frustration_delta = delta
            updated = updated.with_value(
                desire_type,
                updated.get(desire_type).adjusted(
                    level_delta=level_delta,
                    satisfaction_delta=satisfaction_delta,
                    frustration_delta=frustration_delta,
                ),
            )
        return updated

    @staticmethod
    def _update_value_by_elapsed_time(
        value: DesireValue,
        elapsed_minutes: float,
    ) -> DesireValue:
        baseline_ratio = min(1.0, 0.04 * elapsed_minutes)
        level = value.level + (value.baseline - value.level) * baseline_ratio
        satisfaction = max(0.0, value.satisfaction - 0.08 * elapsed_minutes)
        shortage = max(0.0, level - satisfaction - 0.60)
        if shortage > 0.0:
            frustration = value.frustration + shortage * 0.04 * elapsed_minutes
        else:
            frustration = value.frustration - 0.03 * elapsed_minutes
        return replace(
            value,
            level=level,
            satisfaction=satisfaction,
            frustration=frustration,
        )

    def _write_causal_trace(
        self,
        event: AgentEvent,
        before: DesireState,
        after: DesireState,
        *,
        affective_appraisal: AffectiveAppraisal,
        update_source: str,
    ) -> None:
        self._trace_logger.info(
            "desire_state_updater:causal_update",
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            update_source=update_source,
            affective_cause=affective_appraisal.cause_category,
            projection_source=affective_appraisal.projection_source,
            before_effective=before.effective_values(),
            after_effective=after.effective_values(),
        )
