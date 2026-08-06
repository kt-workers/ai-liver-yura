from __future__ import annotations

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_affect import BodyAffectBaseline
from app.domain.body_attention_intent import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjection,
)


class BodyAttentionIntentResolver:
    """Activity overrideと対人的表現、感情回避傾向から注意意図を解決する。"""

    def resolve(
        self,
        *,
        context: BodyActivityContext,
        baseline: BodyAffectBaseline,
        projection: InteractionExpressionProjection | None,
    ) -> BodyAttentionIntent | None:
        if not isinstance(context, BodyActivityContext):
            raise TypeError("context must be BodyActivityContext")
        if not isinstance(baseline, BodyAffectBaseline):
            raise TypeError("baseline must be BodyAffectBaseline")

        projected = projection.attention_intent if projection is not None else None
        target = context.attention_target or (
            projected.target if projected is not None else None
        )
        if target is None:
            return None

        if projected is not None:
            return BodyAttentionIntent(
                target=target,
                behavior=projected.behavior,
                engagement=context.engagement,
                avoidance=max(projected.avoidance, baseline.avoidance * 0.45),
                eye_follow=projected.eye_follow,
                head_follow=projected.head_follow,
                body_follow=projected.body_follow,
            )

        behavior = (
            BodyAttentionBehavior.AVOID
            if baseline.avoidance >= 0.75
            else BodyAttentionBehavior.MAINTAIN
        )
        return BodyAttentionIntent(
            target=target,
            behavior=behavior,
            engagement=context.engagement,
            avoidance=baseline.avoidance,
            eye_follow=0.88,
            head_follow=0.52,
            body_follow=0.16,
        )
