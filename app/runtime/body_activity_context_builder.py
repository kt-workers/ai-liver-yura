from __future__ import annotations

from collections.abc import Mapping

from app.domain.activities import Activity
from app.domain.body import BodyActivityContext, BodyPostureTendency
from app.runtime.body_activity_context_policy import BodyActivityContextPolicy
from app.runtime.body_interaction_intention_resolver import (
    BodyInteractionIntentionResolver,
)
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjector,
)
from app.utils.trace import TraceLogger


class BodyActivityContextBuilder:
    """Body文脈の既定値へ明示overrideを適用し、型付きContextを生成する。"""

    def __init__(
        self,
        projector: InteractionExpressionProjector | None = None,
        intention_resolver: BodyInteractionIntentionResolver | None = None,
        context_policy: BodyActivityContextPolicy | None = None,
    ) -> None:
        self._projector = projector or InteractionExpressionProjector()
        self._intention_resolver = (
            intention_resolver or BodyInteractionIntentionResolver()
        )
        self._context_policy = context_policy or BodyActivityContextPolicy()
        self._trace_logger = TraceLogger()

    def build(self, activity: Activity) -> BodyActivityContext:
        defaults = self._context_policy.defaults_for(activity.activity_type)
        raw = activity.context.get("body_context", {})
        overrides: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}

        intention = self._intention_resolver.resolve(activity)
        projection = self._projector.project(intention) if intention is not None else None
        projected = self._context_policy.apply_projection(defaults, projection)

        context = BodyActivityContext(
            source_activity_id=activity.activity_id,
            attention_target=self._optional_name(
                overrides.get("attention_target"),
                projected.attention_target,
            ),
            engagement=self._unit(
                overrides.get("engagement"),
                projected.engagement,
            ),
            posture_tendency=self._posture(
                overrides.get("posture_tendency"),
                projected.posture_tendency,
            ),
            movement_energy=self._unit(
                overrides.get("movement_energy"),
                projected.movement_energy,
            ),
            gaze_freedom=self._unit(
                overrides.get("gaze_freedom"),
                projected.gaze_freedom,
            ),
            interaction_intention=intention,
        )
        self._trace_projection(activity, context, explicit_override=bool(overrides))
        return context

    def _trace_projection(
        self,
        activity: Activity,
        context: BodyActivityContext,
        *,
        explicit_override: bool,
    ) -> None:
        intention = context.interaction_intention
        if intention is None:
            return
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
            explicit_body_override=explicit_override,
        )

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
