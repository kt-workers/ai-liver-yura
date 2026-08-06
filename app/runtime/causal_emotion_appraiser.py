from __future__ import annotations

from collections.abc import Sequence

from app.domain.emotions import (
    EmotionAppraisal,
    EmotionCause,
    EmotionState,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.relationships import RelationshipState
from app.runtime.emotion_appraiser import EmotionAppraiser
from app.shared.contracts.memory import EmotionHistoryRecord


class CausalEmotionAppraiser(EmotionAppraiser):
    """既存評価へ、Activity結果と新規刺激の感情的意味を補う。"""

    def appraise(
        self,
        event: AgentEvent,
        *,
        current_emotion: EmotionState | None = None,
        relationship: RelationshipState | None = None,
        recent_history: Sequence[EmotionHistoryRecord] = (),
    ) -> EmotionAppraisal:
        if event.event_type == AgentEventType.ACTIVITY_RESULT_RECORDED:
            return self._activity_result_appraisal(event)
        if event.event_type == AgentEventType.TREND_UPDATED:
            return EmotionAppraisal(
                surprise_delta=0.04,
                arousal_delta=0.03,
                talkativeness_delta=0.01,
                reason="new_external_stimulus_observed",
                cause=EmotionCause(
                    category="new_external_stimulus_observed",
                    summary="新しい外部情報を観測した",
                    source_event_id=event.event_id,
                ),
                confidence=0.75,
                source_event_id=event.event_id,
            )
        return super().appraise(
            event,
            current_emotion=current_emotion,
            relationship=relationship,
            recent_history=recent_history,
        )

    @staticmethod
    def _activity_result_appraisal(event: AgentEvent) -> EmotionAppraisal:
        outcome = str(event.payload.get("outcome") or "completed").strip().lower()
        activity_type = str(event.payload.get("activity_type") or "activity").strip()
        if outcome == "failed":
            return EmotionAppraisal(
                anger_delta=0.04,
                sadness_delta=0.035,
                discomfort_delta=0.08,
                pressure_delta=0.05,
                arousal_delta=0.06,
                valence_delta=-0.07,
                talkativeness_delta=-0.015,
                reason="activity_failed",
                cause=EmotionCause(
                    category="activity_failed",
                    summary="取り組んでいたActivityが失敗した",
                    target=activity_type,
                    source_event_id=event.event_id,
                ),
                source_event_id=event.event_id,
            )
        if outcome == "partial":
            return EmotionAppraisal(
                joy_delta=0.015,
                sadness_delta=0.015,
                discomfort_delta=0.02,
                pressure_delta=0.015,
                valence_delta=-0.005,
                reason="activity_partially_completed",
                cause=EmotionCause(
                    category="activity_partially_completed",
                    summary="Activityは一部だけ達成できた",
                    target=activity_type,
                    source_event_id=event.event_id,
                ),
                source_event_id=event.event_id,
            )
        if outcome == "canceled":
            return EmotionAppraisal(
                sadness_delta=0.02,
                discomfort_delta=0.015,
                pressure_delta=0.01,
                arousal_delta=-0.01,
                valence_delta=-0.025,
                reason="activity_canceled",
                cause=EmotionCause(
                    category="activity_canceled",
                    summary="Activityを途中でやめた",
                    target=activity_type,
                    source_event_id=event.event_id,
                ),
                source_event_id=event.event_id,
            )
        return EmotionAppraisal(
            joy_delta=0.025,
            pressure_delta=-0.02,
            valence_delta=0.025,
            reason="activity_completed",
            cause=EmotionCause(
                category="activity_completed",
                summary="取り組んでいたActivityを完了した",
                target=activity_type,
                source_event_id=event.event_id,
            ),
            source_event_id=event.event_id,
        )
