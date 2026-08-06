from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_activity_context import BodyPostureTendency
from app.domain.body_attention_intent import BodyAttentionIntent
from app.domain.body_expression import EmbodiedExpressionIntent
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.interaction_expression_profiles import (
    INTERACTION_EXPRESSION_PROFILES,
    InteractionExpressionProfile,
)


@dataclass(frozen=True, slots=True)
class InteractionExpressionProjection:
    """CharacterとBodyが共有する、実行権限を持たない表現方向。"""

    embodied_expression: EmbodiedExpressionIntent
    attention_intent: BodyAttentionIntent | None
    posture_tendency: BodyPostureTendency
    movement_energy: float
    gaze_freedom: float
    content_strategy: str

    def as_context(self) -> dict[str, object]:
        return {
            "embodied_expression": self.embodied_expression.as_payload(),
            "attention_intent": (
                self.attention_intent.as_payload()
                if self.attention_intent is not None
                else None
            ),
            "posture_tendency": self.posture_tendency.value,
            "movement_energy": self.movement_energy,
            "gaze_freedom": self.gaze_freedom,
            "content_strategy": self.content_strategy,
            "observation_only": True,
            "grants_execution_authority": False,
        }


class InteractionExpressionProjector:
    """有限な対人的意図とProfileを高レベル表現契約へ射影する。"""

    def project(
        self,
        intention: InteractionIntention,
    ) -> InteractionExpressionProjection:
        if not isinstance(intention, InteractionIntention):
            raise TypeError("intention must be InteractionIntention")
        profile = INTERACTION_EXPRESSION_PROFILES.get(
            intention.intention,
            INTERACTION_EXPRESSION_PROFILES[InteractionIntentionType.OBSERVE],
        )
        return self._from_profile(
            profile=profile,
            target=self._target(intention),
        )

    @staticmethod
    def _target(intention: InteractionIntention) -> str:
        value = intention.target_id or intention.target_type or "conversation_partner"
        normalized = value.strip() or "conversation_partner"
        return normalized[:80]

    @staticmethod
    def _from_profile(
        *,
        profile: InteractionExpressionProfile,
        target: str,
    ) -> InteractionExpressionProjection:
        return InteractionExpressionProjection(
            embodied_expression=EmbodiedExpressionIntent(
                attitude=profile.attitude,
                intensity=profile.intensity,
                valence=profile.valence,
                arousal=profile.arousal,
                tension=profile.tension,
                openness=profile.openness,
                approach=profile.approach,
                agreement=profile.agreement,
                surprise=profile.surprise,
                assertiveness=profile.assertiveness,
                warmth=profile.warmth,
            ),
            attention_intent=BodyAttentionIntent(
                target=target,
                behavior=profile.attention_behavior,
                engagement=profile.engagement,
                avoidance=profile.avoidance,
                eye_follow=0.92,
                head_follow=0.56,
                body_follow=0.18,
            ),
            posture_tendency=profile.posture,
            movement_energy=profile.movement_energy,
            gaze_freedom=profile.gaze_freedom,
            content_strategy=profile.content_strategy,
        )
