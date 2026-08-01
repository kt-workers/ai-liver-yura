from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

from app.domain.desires import DesireState, DesireType, DesireValue
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_desire_satisfaction_evaluator import (
    ActivityDesireSatisfactionEvaluator,
)


DesireDelta = tuple[float, float, float]


class DesireStateUpdater:
    """Eventと経過時間から、観測用のDesireStateを更新する。"""

    _USER_INPUT_DELTAS: Mapping[DesireType, DesireDelta] = {
        DesireType.CONNECTION: (0.06, 0.0, 0.0),
        DesireType.CURIOSITY: (0.04, 0.0, 0.0),
        DesireType.EXPRESSION: (0.02, 0.0, 0.0),
        DesireType.RECOGNITION: (0.01, 0.0, 0.0),
    }

    def __init__(
        self,
        *,
        activity_result_evaluator: ActivityDesireSatisfactionEvaluator | None = None,
    ) -> None:
        self._activity_result_evaluator = (
            activity_result_evaluator or ActivityDesireSatisfactionEvaluator()
        )

    def update_by_event(
        self,
        desire: DesireState,
        event: AgentEvent,
    ) -> DesireState:
        """既存Eventの意味に応じて欲望を更新する。"""

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
            AgentEventType.SPEECH_FINISHED: {
                DesireType.CONNECTION: (0.0, 0.02, 0.0),
                DesireType.EXPRESSION: (0.0, 0.10, 0.0),
                DesireType.ACHIEVEMENT: (0.0, 0.02, 0.0),
            },
            AgentEventType.STREAM_COMMENT_RESPONSE: {
                DesireType.CONNECTION: (0.0, 0.04, 0.0),
                DesireType.RECOGNITION: (0.0, 0.03, 0.0),
            },
            AgentEventType.ACTION_FAILED: {
                DesireType.SECURITY: (0.04, 0.0, 0.0),
                DesireType.ACHIEVEMENT: (0.05, 0.0, 0.08),
            },
            AgentEventType.STREAM_ENDED: {
                DesireType.EXPRESSION: (0.0, 0.04, 0.0),
                DesireType.RECOGNITION: (0.0, 0.06, 0.0),
                DesireType.ACHIEVEMENT: (0.0, 0.10, 0.0),
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
