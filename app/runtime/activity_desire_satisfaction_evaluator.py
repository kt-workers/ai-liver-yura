from __future__ import annotations

from collections.abc import Mapping

from app.domain.activities import ActivityType
from app.domain.desires import DesireType
from app.domain.events import AgentEvent, AgentEventType


DesireDelta = tuple[float, float, float]


class ActivityDesireSatisfactionEvaluator:
    """Activity結果を、欲望の充足・不満の観測値へ変換する。"""

    _SUCCESS_DELTAS: Mapping[
        ActivityType,
        Mapping[DesireType, DesireDelta],
    ] = {
        ActivityType.CONVERSATION_WITH_USER: {
            DesireType.CONNECTION: (0.0, 0.08, 0.0),
            DesireType.EXPRESSION: (0.0, 0.04, 0.0),
        },
        ActivityType.DIRECTED_TALK: {
            DesireType.EXPRESSION: (0.0, 0.07, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.05, 0.0),
        },
        ActivityType.AUTONOMOUS_TALK: {
            DesireType.EXPRESSION: (0.0, 0.08, 0.0),
            DesireType.AUTONOMY: (0.0, 0.05, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.03, 0.0),
        },
        ActivityType.STIMULUS_REACTION: {
            DesireType.CONNECTION: (0.0, 0.03, 0.0),
            DesireType.EXPRESSION: (0.0, 0.03, 0.0),
        },
        ActivityType.CURIOSITY_RESEARCH: {
            DesireType.CURIOSITY: (0.0, 0.10, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.04, 0.0),
        },
        ActivityType.TOPIC_EXPLORATION: {
            DesireType.CURIOSITY: (0.0, 0.08, 0.0),
            DesireType.EXPRESSION: (0.0, 0.04, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.03, 0.0),
        },
        ActivityType.EXTERNAL_TREND_WATCH: {
            DesireType.CURIOSITY: (0.0, 0.08, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.04, 0.0),
        },
        ActivityType.STREAM_OPENING_GREETING: {
            DesireType.EXPRESSION: (0.0, 0.06, 0.0),
            DesireType.RECOGNITION: (0.0, 0.04, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.04, 0.0),
        },
        ActivityType.STREAM_MAIN_SEGMENT: {
            DesireType.EXPRESSION: (0.0, 0.08, 0.0),
            DesireType.RECOGNITION: (0.0, 0.05, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.07, 0.0),
        },
        ActivityType.STREAM_COMMENT_RESPONSE: {
            DesireType.CONNECTION: (0.0, 0.07, 0.0),
            DesireType.RECOGNITION: (0.0, 0.04, 0.0),
            DesireType.EXPRESSION: (0.0, 0.03, 0.0),
        },
        ActivityType.STREAM_CLOSING_GREETING: {
            DesireType.CONNECTION: (0.0, 0.04, 0.0),
            DesireType.EXPRESSION: (0.0, 0.05, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.08, 0.0),
        },
        ActivityType.PLUGIN_ACTIVITY: {
            DesireType.AUTONOMY: (0.0, 0.03, 0.0),
            DesireType.ACHIEVEMENT: (0.0, 0.05, 0.0),
        },
        ActivityType.BODY_EXPRESSION_LOOP: {
            DesireType.EXPRESSION: (0.0, 0.06, 0.0),
        },
        ActivityType.LISTENING_MODE: {
            DesireType.CONNECTION: (0.0, 0.03, 0.0),
            DesireType.SECURITY: (0.0, 0.02, 0.0),
        },
        ActivityType.IDLE_OBSERVATION: {
            DesireType.CURIOSITY: (0.0, 0.02, 0.0),
            DesireType.SECURITY: (0.0, 0.02, 0.0),
        },
        ActivityType.AWAKENING: {
            DesireType.SECURITY: (0.0, 0.03, 0.0),
            DesireType.AUTONOMY: (0.0, 0.02, 0.0),
        },
        ActivityType.STARTUP_REACTION: {
            DesireType.EXPRESSION: (0.0, 0.03, 0.0),
        },
    }

    _SOCIAL_ACTIVITIES = frozenset(
        {
            ActivityType.CONVERSATION_WITH_USER,
            ActivityType.STIMULUS_REACTION,
            ActivityType.STREAM_COMMENT_RESPONSE,
            ActivityType.LISTENING_MODE,
        }
    )
    _EXPLORATION_ACTIVITIES = frozenset(
        {
            ActivityType.CURIOSITY_RESEARCH,
            ActivityType.TOPIC_EXPLORATION,
            ActivityType.EXTERNAL_TREND_WATCH,
        }
    )

    def evaluate(
        self,
        event: AgentEvent,
    ) -> Mapping[DesireType, DesireDelta]:
        if event.event_type != AgentEventType.ACTIVITY_RESULT_RECORDED:
            return {}

        activity_type_value = event.payload.get("activity_type")
        outcome = event.payload.get("outcome")
        try:
            activity_type = ActivityType(str(activity_type_value))
        except ValueError:
            return {}

        success = self._SUCCESS_DELTAS.get(activity_type, {})
        if outcome == "completed":
            return success
        if outcome == "partial":
            return self._partial_deltas(activity_type, success)
        if outcome == "canceled":
            return self._canceled_deltas(activity_type)
        if outcome == "failed":
            return self._failed_deltas(activity_type)
        return {}

    @staticmethod
    def _scale(
        deltas: Mapping[DesireType, DesireDelta],
        factor: float,
    ) -> dict[DesireType, DesireDelta]:
        return {
            desire_type: (
                level_delta * factor,
                satisfaction_delta * factor,
                frustration_delta * factor,
            )
            for desire_type, (
                level_delta,
                satisfaction_delta,
                frustration_delta,
            ) in deltas.items()
        }

    def _partial_deltas(
        self,
        activity_type: ActivityType,
        success: Mapping[DesireType, DesireDelta],
    ) -> Mapping[DesireType, DesireDelta]:
        result = self._scale(success, 0.5)
        achievement = result.get(DesireType.ACHIEVEMENT, (0.0, 0.0, 0.0))
        result[DesireType.ACHIEVEMENT] = (
            achievement[0] + 0.01,
            achievement[1],
            achievement[2] + 0.02,
        )
        if activity_type in self._SOCIAL_ACTIVITIES:
            connection = result.get(DesireType.CONNECTION, (0.0, 0.0, 0.0))
            result[DesireType.CONNECTION] = (
                connection[0],
                connection[1],
                connection[2] + 0.01,
            )
        return result

    def _failed_deltas(
        self,
        activity_type: ActivityType,
    ) -> Mapping[DesireType, DesireDelta]:
        result: dict[DesireType, DesireDelta] = {
            DesireType.SECURITY: (0.03, 0.0, 0.0),
            DesireType.ACHIEVEMENT: (0.04, 0.0, 0.07),
        }
        if activity_type in self._SOCIAL_ACTIVITIES:
            result[DesireType.CONNECTION] = (0.02, 0.0, 0.03)
        if activity_type in self._EXPLORATION_ACTIVITIES:
            result[DesireType.CURIOSITY] = (0.03, 0.0, 0.04)
        return result

    def _canceled_deltas(
        self,
        activity_type: ActivityType,
    ) -> Mapping[DesireType, DesireDelta]:
        result: dict[DesireType, DesireDelta] = {
            DesireType.ACHIEVEMENT: (0.01, 0.0, 0.02),
        }
        if activity_type in self._SOCIAL_ACTIVITIES:
            result[DesireType.CONNECTION] = (0.01, 0.0, 0.01)
        if activity_type in self._EXPLORATION_ACTIVITIES:
            result[DesireType.CURIOSITY] = (0.01, 0.0, 0.02)
        return result
