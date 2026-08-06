from __future__ import annotations

from collections.abc import Mapping

from app.domain.activities import Activity, ActivityType
from app.domain.body import BodyActivityContext, BodyPostureTendency
from app.domain.interaction_intention import InteractionIntention
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjection,
    InteractionExpressionProjector,
)
from app.utils.trace import TraceLogger


class BodyActivityContextBuilder:
    """Activityを毎フレーム命令ではない継続的な身体文脈へ変換する。"""

    _DEFAULTS: dict[
        ActivityType,
        tuple[str | None, float, BodyPostureTendency, float, float],
    ] = {
        ActivityType.CONVERSATION_WITH_USER: (
            "conversation_partner",
            0.72,
            BodyPostureTendency.OPEN,
            0.38,
            0.25,
        ),
        ActivityType.DIRECTED_TALK: (
            "audience",
            0.68,
            BodyPostureTendency.OPEN,
            0.46,
            0.32,
        ),
        ActivityType.LISTENING_MODE: (
            "conversation_partner",
            0.82,
            BodyPostureTendency.FORWARD,
            0.24,
            0.18,
        ),
        ActivityType.STIMULUS_REACTION: (
            "stimulus",
            0.78,
            BodyPostureTendency.NEUTRAL,
            0.58,
            0.42,
        ),
        ActivityType.IDLE_OBSERVATION: (
            None,
            0.25,
            BodyPostureTendency.NEUTRAL,
            0.22,
            0.88,
        ),
        ActivityType.BODY_EXPRESSION_LOOP: (
            None,
            0.35,
            BodyPostureTendency.NEUTRAL,
            0.32,
            0.72,
        ),
    }

    def __init__(
        self,
        projector: InteractionExpressionProjector | None = None,
    ) -> None:
        self._projector = projector or InteractionExpressionProjector()
        self._trace_logger = TraceLogger()

    def build(self, activity: Activity) -> BodyActivityContext:
        defaults = self._DEFAULTS.get(
            activity.activity_type,
            (
                None,
                0.5,
                BodyPostureTendency.NEUTRAL,
                0.35,
                0.5,
            ),
        )
        raw = activity.context.get("body_context", {})
        overrides: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}
        intention = self._interaction_intention(activity)
        projection = self._projector.project(intention) if intention is not None else None
        projected_defaults = self._projected_defaults(defaults, projection)

        attention_target = self._optional_name(
            overrides.get("attention_target"),
            projected_defaults[0],
        )
        posture_tendency = self._posture(
            overrides.get("posture_tendency"),
            projected_defaults[2],
        )
        context = BodyActivityContext(
            source_activity_id=activity.activity_id,
            attention_target=attention_target,
            engagement=self._unit(
                overrides.get("engagement"),
                projected_defaults[1],
            ),
            posture_tendency=posture_tendency,
            movement_energy=self._unit(
                overrides.get("movement_energy"),
                projected_defaults[3],
            ),
            gaze_freedom=self._unit(
                overrides.get("gaze_freedom"),
                projected_defaults[4],
            ),
            interaction_intention=intention,
        )
        if intention is not None:
            self._trace_logger.info(
                "interaction_intention:body_context_projected",
                source_activity_id=activity.activity_id,
                activity_type=activity.activity_type.value,
                intention=intention.intention.value,
                intention_source=intention.source,
                observation_only=intention.observation_only,
                posture_tendency=context.posture_tendency.value,
                attention_target=context.attention_target,
                engagement=context.engagement,
                movement_energy=context.movement_energy,
                gaze_freedom=context.gaze_freedom,
                explicit_body_override=bool(overrides),
            )
        return context

    @staticmethod
    def _projected_defaults(
        defaults: tuple[str | None, float, BodyPostureTendency, float, float],
        projection: InteractionExpressionProjection | None,
    ) -> tuple[str | None, float, BodyPostureTendency, float, float]:
        if projection is None:
            return defaults
        attention = projection.attention_intent
        attention_target = attention.target if attention is not None else defaults[0]
        attention_engagement = (
            attention.engagement if attention is not None else defaults[1]
        )
        return (
            attention_target,
            BodyActivityContextBuilder._blend(defaults[1], attention_engagement),
            projection.posture_tendency,
            BodyActivityContextBuilder._blend(
                defaults[3], projection.movement_energy
            ),
            BodyActivityContextBuilder._blend(
                defaults[4], projection.gaze_freedom
            ),
        )

    @staticmethod
    def _interaction_intention(activity: Activity) -> InteractionIntention | None:
        candidates: list[object] = [activity.context.get("interaction_intention")]
        event_payload = activity.context.get("event_payload")
        if isinstance(event_payload, Mapping):
            candidates.append(event_payload.get("interaction_intention"))
        behavior_plan = activity.context.get("behavior_plan")
        if isinstance(behavior_plan, Mapping):
            candidates.append(behavior_plan.get("interaction_intention"))
        for candidate in candidates:
            intention = InteractionIntention.from_context(candidate)
            if intention is not None:
                return intention
        return None

    @staticmethod
    def _blend(base: float, projected: float) -> float:
        return max(0.0, min(1.0, base * 0.45 + projected * 0.55))

    @staticmethod
    def _unit(value: object, default: float) -> float:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0.0 <= float(value) <= 1.0
        ):
            return float(value)
        return default

    @staticmethod
    def _optional_name(value: object, default: str | None) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    @staticmethod
    def _posture(
        value: object,
        default: BodyPostureTendency,
    ) -> BodyPostureTendency:
        if isinstance(value, BodyPostureTendency):
            return value
        if isinstance(value, str):
            try:
                return BodyPostureTendency(value.strip())
            except ValueError:
                pass
        return default
