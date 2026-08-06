from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_activity_context import BodyPostureTendency
from app.domain.body_attention_intent import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)
from app.domain.body_expression import EmbodiedExpressionIntent
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
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
        expression = self.embodied_expression
        attention = self.attention_intent
        return {
            "embodied_expression": expression.as_payload(),
            "attention_intent": (
                attention.as_payload() if attention is not None else None
            ),
            "posture_tendency": self.posture_tendency.value,
            "movement_energy": self.movement_energy,
            "gaze_freedom": self.gaze_freedom,
            "content_strategy": self.content_strategy,
            "observation_only": True,
            "grants_execution_authority": False,
        }


class InteractionExpressionProjector:
    """有限な対人的意図を、モーション名に依存しない表現へ射影する。"""

    def project(
        self,
        intention: InteractionIntention,
    ) -> InteractionExpressionProjection:
        kind = intention.intention
        target = self._target(intention)
        if kind is InteractionIntentionType.ANSWER:
            return self._projection(
                attitude="direct",
                intensity=0.52,
                valence=0.08,
                arousal=0.42,
                openness=0.62,
                approach=0.24,
                assertiveness=0.58,
                warmth=0.56,
                posture=BodyPostureTendency.FORWARD,
                target=target,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=0.82,
                movement_energy=0.38,
                gaze_freedom=0.18,
                content_strategy="answer_directly",
            )
        if kind is InteractionIntentionType.ACKNOWLEDGE:
            return self._projection(
                attitude="receptive",
                intensity=0.34,
                valence=0.18,
                arousal=0.30,
                openness=0.66,
                agreement=0.42,
                warmth=0.68,
                posture=BodyPostureTendency.OPEN,
                target=target,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=0.74,
                movement_energy=0.28,
                gaze_freedom=0.22,
                content_strategy="acknowledge_briefly",
            )
        if kind is InteractionIntentionType.LISTEN:
            return self._projection(
                attitude="listening",
                intensity=0.28,
                valence=0.06,
                arousal=0.24,
                openness=0.72,
                approach=0.20,
                warmth=0.66,
                posture=BodyPostureTendency.FORWARD,
                target=target,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=0.88,
                movement_energy=0.20,
                gaze_freedom=0.12,
                content_strategy="leave_room_for_other",
            )
        if kind is InteractionIntentionType.ASK:
            return self._projection(
                attitude="curious",
                intensity=0.48,
                valence=0.12,
                arousal=0.52,
                openness=0.72,
                approach=0.32,
                surprise=0.14,
                warmth=0.58,
                posture=BodyPostureTendency.FORWARD,
                target=target,
                behavior=BodyAttentionBehavior.SEARCH,
                engagement=0.82,
                movement_energy=0.42,
                gaze_freedom=0.34,
                content_strategy="ask_one_grounded_question",
            )
        if kind is InteractionIntentionType.SHARE:
            return self._projection(
                attitude="expressive",
                intensity=0.54,
                valence=0.16,
                arousal=0.50,
                openness=0.76,
                approach=0.26,
                assertiveness=0.42,
                warmth=0.62,
                posture=BodyPostureTendency.OPEN,
                target=target,
                behavior=BodyAttentionBehavior.GLANCE,
                engagement=0.68,
                movement_energy=0.48,
                gaze_freedom=0.46,
                content_strategy="share_one_thought",
            )
        if kind is InteractionIntentionType.INVITE:
            return self._projection(
                attitude="welcoming",
                intensity=0.50,
                valence=0.28,
                arousal=0.44,
                openness=0.84,
                approach=0.38,
                agreement=0.18,
                warmth=0.80,
                posture=BodyPostureTendency.OPEN,
                target=target,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=0.84,
                movement_energy=0.42,
                gaze_freedom=0.24,
                content_strategy="invite_without_pressure",
            )
        if kind is InteractionIntentionType.COMFORT:
            return self._projection(
                attitude="gentle",
                intensity=0.40,
                valence=0.10,
                arousal=0.22,
                tension=0.12,
                openness=0.70,
                approach=0.24,
                warmth=0.92,
                posture=BodyPostureTendency.FORWARD,
                target=target,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=0.84,
                movement_energy=0.18,
                gaze_freedom=0.10,
                content_strategy="comfort_without_assuming",
            )
        if kind is InteractionIntentionType.SET_BOUNDARY:
            return self._projection(
                attitude="guarded",
                intensity=0.68,
                valence=-0.28,
                arousal=0.48,
                tension=0.58,
                openness=0.18,
                approach=-0.36,
                assertiveness=0.82,
                warmth=0.24,
                posture=BodyPostureTendency.CLOSED,
                target=target,
                behavior=BodyAttentionBehavior.AVOID,
                engagement=0.38,
                avoidance=0.72,
                movement_energy=0.30,
                gaze_freedom=0.20,
                content_strategy="state_boundary_calmly",
            )
        if kind is InteractionIntentionType.PAUSE:
            return self._projection(
                attitude="restrained",
                intensity=0.18,
                valence=0.0,
                arousal=0.16,
                tension=0.18,
                openness=0.30,
                approach=-0.12,
                warmth=0.44,
                posture=BodyPostureTendency.WITHDRAWN,
                target=target,
                behavior=BodyAttentionBehavior.GLANCE,
                engagement=0.30,
                movement_energy=0.12,
                gaze_freedom=0.52,
                content_strategy="do_not_claim_the_turn",
            )
        if kind is InteractionIntentionType.ACT:
            return self._projection(
                attitude="focused",
                intensity=0.48,
                valence=0.02,
                arousal=0.46,
                openness=0.44,
                approach=0.22,
                assertiveness=0.62,
                warmth=0.46,
                posture=BodyPostureTendency.NEUTRAL,
                target=target,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=0.72,
                movement_energy=0.44,
                gaze_freedom=0.20,
                content_strategy="describe_only_confirmed_execution_state",
            )
        return self._projection(
            attitude="observant",
            intensity=0.22,
            valence=0.0,
            arousal=0.24,
            openness=0.48,
            warmth=0.48,
            posture=BodyPostureTendency.NEUTRAL,
            target=target,
            behavior=BodyAttentionBehavior.WANDER,
            engagement=0.34,
            movement_energy=0.18,
            gaze_freedom=0.82,
            content_strategy="observe_without_expanding",
        )

    @staticmethod
    def _target(intention: InteractionIntention) -> str:
        value = intention.target_id or intention.target_type or "conversation_partner"
        normalized = value.strip() or "conversation_partner"
        return normalized[:80]

    @staticmethod
    def _projection(
        *,
        attitude: str,
        intensity: float,
        valence: float,
        arousal: float,
        openness: float,
        warmth: float,
        posture: BodyPostureTendency,
        target: str,
        behavior: BodyAttentionBehavior,
        engagement: float,
        movement_energy: float,
        gaze_freedom: float,
        content_strategy: str,
        tension: float = 0.0,
        approach: float = 0.0,
        agreement: float = 0.0,
        surprise: float = 0.0,
        assertiveness: float = 0.0,
        avoidance: float = 0.0,
    ) -> InteractionExpressionProjection:
        return InteractionExpressionProjection(
            embodied_expression=EmbodiedExpressionIntent(
                attitude=attitude,
                intensity=intensity,
                valence=valence,
                arousal=arousal,
                tension=tension,
                openness=openness,
                approach=approach,
                agreement=agreement,
                surprise=surprise,
                assertiveness=assertiveness,
                warmth=warmth,
            ),
            attention_intent=BodyAttentionIntent(
                target=target,
                behavior=behavior,
                engagement=engagement,
                avoidance=avoidance,
                eye_follow=0.92,
                head_follow=0.56,
                body_follow=0.18,
            ),
            posture_tendency=posture,
            movement_energy=movement_energy,
            gaze_freedom=gaze_freedom,
            content_strategy=content_strategy,
        )
