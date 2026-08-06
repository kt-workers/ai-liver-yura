from __future__ import annotations

from dataclasses import dataclass

from app.domain.activities import ActivityType
from app.domain.body_activity_context import BodyPostureTendency
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjection,
)


@dataclass(frozen=True, slots=True)
class BodyActivityContextDefaults:
    """Activity種別と表現意図から得るBody Contextの既定値。"""

    attention_target: str | None
    engagement: float
    posture_tendency: BodyPostureTendency
    movement_energy: float
    gaze_freedom: float


class BodyActivityContextPolicy:
    """Activity既定値とInteraction Expression射影を合成する。"""

    _DEFAULTS: dict[ActivityType, BodyActivityContextDefaults] = {
        ActivityType.CONVERSATION_WITH_USER: BodyActivityContextDefaults(
            attention_target="conversation_partner",
            engagement=0.72,
            posture_tendency=BodyPostureTendency.OPEN,
            movement_energy=0.38,
            gaze_freedom=0.25,
        ),
        ActivityType.DIRECTED_TALK: BodyActivityContextDefaults(
            attention_target="audience",
            engagement=0.68,
            posture_tendency=BodyPostureTendency.OPEN,
            movement_energy=0.46,
            gaze_freedom=0.32,
        ),
        ActivityType.LISTENING_MODE: BodyActivityContextDefaults(
            attention_target="conversation_partner",
            engagement=0.82,
            posture_tendency=BodyPostureTendency.FORWARD,
            movement_energy=0.24,
            gaze_freedom=0.18,
        ),
        ActivityType.STIMULUS_REACTION: BodyActivityContextDefaults(
            attention_target="stimulus",
            engagement=0.78,
            posture_tendency=BodyPostureTendency.NEUTRAL,
            movement_energy=0.58,
            gaze_freedom=0.42,
        ),
        ActivityType.IDLE_OBSERVATION: BodyActivityContextDefaults(
            attention_target=None,
            engagement=0.25,
            posture_tendency=BodyPostureTendency.NEUTRAL,
            movement_energy=0.22,
            gaze_freedom=0.88,
        ),
        ActivityType.BODY_EXPRESSION_LOOP: BodyActivityContextDefaults(
            attention_target=None,
            engagement=0.35,
            posture_tendency=BodyPostureTendency.NEUTRAL,
            movement_energy=0.32,
            gaze_freedom=0.72,
        ),
    }
    _FALLBACK = BodyActivityContextDefaults(
        attention_target=None,
        engagement=0.5,
        posture_tendency=BodyPostureTendency.NEUTRAL,
        movement_energy=0.35,
        gaze_freedom=0.5,
    )

    def defaults_for(self, activity_type: ActivityType) -> BodyActivityContextDefaults:
        return self._DEFAULTS.get(activity_type, self._FALLBACK)

    def apply_projection(
        self,
        defaults: BodyActivityContextDefaults,
        projection: InteractionExpressionProjection | None,
    ) -> BodyActivityContextDefaults:
        if projection is None:
            return defaults
        attention = projection.attention_intent
        return BodyActivityContextDefaults(
            attention_target=(
                attention.target if attention is not None else defaults.attention_target
            ),
            engagement=self._blend(
                defaults.engagement,
                attention.engagement if attention is not None else defaults.engagement,
            ),
            posture_tendency=projection.posture_tendency,
            movement_energy=self._blend(
                defaults.movement_energy,
                projection.movement_energy,
            ),
            gaze_freedom=self._blend(
                defaults.gaze_freedom,
                projection.gaze_freedom,
            ),
        )

    @staticmethod
    def _blend(base: float, projected: float) -> float:
        return max(0.0, min(1.0, base * 0.45 + projected * 0.55))
