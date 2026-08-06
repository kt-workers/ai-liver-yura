from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_activity_context import BodyPostureTendency
from app.domain.body_attention_intent import BodyAttentionBehavior
from app.domain.interaction_intention import InteractionIntentionType


@dataclass(frozen=True, slots=True)
class InteractionExpressionProfile:
    """Interaction Intentionごとのモデル非依存な表現Profile。"""

    attitude: str
    intensity: float
    valence: float
    arousal: float
    openness: float
    warmth: float
    posture: BodyPostureTendency
    attention_behavior: BodyAttentionBehavior
    engagement: float
    movement_energy: float
    gaze_freedom: float
    content_strategy: str
    tension: float = 0.0
    approach: float = 0.0
    agreement: float = 0.0
    surprise: float = 0.0
    assertiveness: float = 0.0
    avoidance: float = 0.0


INTERACTION_EXPRESSION_PROFILES: dict[
    InteractionIntentionType,
    InteractionExpressionProfile,
] = {
    InteractionIntentionType.ANSWER: InteractionExpressionProfile(
        attitude="direct",
        intensity=0.52,
        valence=0.08,
        arousal=0.42,
        openness=0.62,
        approach=0.24,
        assertiveness=0.58,
        warmth=0.56,
        posture=BodyPostureTendency.FORWARD,
        attention_behavior=BodyAttentionBehavior.MAINTAIN,
        engagement=0.82,
        movement_energy=0.38,
        gaze_freedom=0.18,
        content_strategy="answer_directly",
    ),
    InteractionIntentionType.ACKNOWLEDGE: InteractionExpressionProfile(
        attitude="receptive",
        intensity=0.34,
        valence=0.18,
        arousal=0.30,
        openness=0.66,
        agreement=0.42,
        warmth=0.68,
        posture=BodyPostureTendency.OPEN,
        attention_behavior=BodyAttentionBehavior.MAINTAIN,
        engagement=0.74,
        movement_energy=0.28,
        gaze_freedom=0.22,
        content_strategy="acknowledge_briefly",
    ),
    InteractionIntentionType.LISTEN: InteractionExpressionProfile(
        attitude="listening",
        intensity=0.28,
        valence=0.06,
        arousal=0.24,
        openness=0.72,
        approach=0.20,
        warmth=0.66,
        posture=BodyPostureTendency.FORWARD,
        attention_behavior=BodyAttentionBehavior.MAINTAIN,
        engagement=0.88,
        movement_energy=0.20,
        gaze_freedom=0.12,
        content_strategy="leave_room_for_other",
    ),
    InteractionIntentionType.ASK: InteractionExpressionProfile(
        attitude="curious",
        intensity=0.48,
        valence=0.12,
        arousal=0.52,
        openness=0.72,
        approach=0.32,
        surprise=0.14,
        warmth=0.58,
        posture=BodyPostureTendency.FORWARD,
        attention_behavior=BodyAttentionBehavior.SEARCH,
        engagement=0.82,
        movement_energy=0.42,
        gaze_freedom=0.34,
        content_strategy="ask_one_grounded_question",
    ),
    InteractionIntentionType.SHARE: InteractionExpressionProfile(
        attitude="expressive",
        intensity=0.54,
        valence=0.16,
        arousal=0.50,
        openness=0.76,
        approach=0.26,
        assertiveness=0.42,
        warmth=0.62,
        posture=BodyPostureTendency.OPEN,
        attention_behavior=BodyAttentionBehavior.GLANCE,
        engagement=0.68,
        movement_energy=0.48,
        gaze_freedom=0.46,
        content_strategy="share_one_thought",
    ),
    InteractionIntentionType.INVITE: InteractionExpressionProfile(
        attitude="welcoming",
        intensity=0.50,
        valence=0.28,
        arousal=0.44,
        openness=0.84,
        approach=0.38,
        agreement=0.18,
        warmth=0.80,
        posture=BodyPostureTendency.OPEN,
        attention_behavior=BodyAttentionBehavior.MAINTAIN,
        engagement=0.84,
        movement_energy=0.42,
        gaze_freedom=0.24,
        content_strategy="invite_without_pressure",
    ),
    InteractionIntentionType.COMFORT: InteractionExpressionProfile(
        attitude="gentle",
        intensity=0.40,
        valence=0.10,
        arousal=0.22,
        tension=0.12,
        openness=0.70,
        approach=0.24,
        warmth=0.92,
        posture=BodyPostureTendency.FORWARD,
        attention_behavior=BodyAttentionBehavior.MAINTAIN,
        engagement=0.84,
        movement_energy=0.18,
        gaze_freedom=0.10,
        content_strategy="comfort_without_assuming",
    ),
    InteractionIntentionType.SET_BOUNDARY: InteractionExpressionProfile(
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
        attention_behavior=BodyAttentionBehavior.AVOID,
        engagement=0.38,
        avoidance=0.72,
        movement_energy=0.30,
        gaze_freedom=0.20,
        content_strategy="state_boundary_calmly",
    ),
    InteractionIntentionType.PAUSE: InteractionExpressionProfile(
        attitude="restrained",
        intensity=0.18,
        valence=0.0,
        arousal=0.16,
        tension=0.18,
        openness=0.30,
        approach=-0.12,
        warmth=0.44,
        posture=BodyPostureTendency.WITHDRAWN,
        attention_behavior=BodyAttentionBehavior.GLANCE,
        engagement=0.30,
        movement_energy=0.12,
        gaze_freedom=0.52,
        content_strategy="do_not_claim_the_turn",
    ),
    InteractionIntentionType.ACT: InteractionExpressionProfile(
        attitude="focused",
        intensity=0.48,
        valence=0.02,
        arousal=0.46,
        openness=0.44,
        approach=0.22,
        assertiveness=0.62,
        warmth=0.46,
        posture=BodyPostureTendency.NEUTRAL,
        attention_behavior=BodyAttentionBehavior.MAINTAIN,
        engagement=0.72,
        movement_energy=0.44,
        gaze_freedom=0.20,
        content_strategy="describe_only_confirmed_execution_state",
    ),
    InteractionIntentionType.OBSERVE: InteractionExpressionProfile(
        attitude="observant",
        intensity=0.22,
        valence=0.0,
        arousal=0.24,
        openness=0.48,
        warmth=0.48,
        posture=BodyPostureTendency.NEUTRAL,
        attention_behavior=BodyAttentionBehavior.WANDER,
        engagement=0.34,
        movement_energy=0.18,
        gaze_freedom=0.82,
        content_strategy="observe_without_expanding",
    ),
}
