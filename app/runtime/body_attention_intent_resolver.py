from __future__ import annotations

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_affect import BodyAffectBaseline
from app.domain.body_attention_intent import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)


class BodyAttentionIntentResolver:
    """Activity override・優先Attention・感情回避傾向から注意意図を解決する。"""

    def resolve(
        self,
        *,
        context: BodyActivityContext,
        baseline: BodyAffectBaseline,
        preferred_attention: BodyAttentionIntent | None,
    ) -> BodyAttentionIntent | None:
        if not isinstance(context, BodyActivityContext):
            raise TypeError("context must be BodyActivityContext")
        if not isinstance(baseline, BodyAffectBaseline):
            raise TypeError("baseline must be BodyAffectBaseline")
        if preferred_attention is not None and not isinstance(
            preferred_attention,
            BodyAttentionIntent,
        ):
            raise TypeError("preferred_attention must be BodyAttentionIntent")

        target = context.attention_target or (
            preferred_attention.target if preferred_attention is not None else None
        )
        if target is None:
            return None

        if preferred_attention is not None:
            return BodyAttentionIntent(
                target=target,
                behavior=preferred_attention.behavior,
                engagement=context.engagement,
                avoidance=max(
                    preferred_attention.avoidance,
                    baseline.avoidance * 0.45,
                ),
                eye_follow=preferred_attention.eye_follow,
                head_follow=preferred_attention.head_follow,
                body_follow=preferred_attention.body_follow,
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
