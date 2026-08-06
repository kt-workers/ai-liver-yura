from __future__ import annotations

import pytest

from app.domain.body import (
    BodyActivityContext as FacadeBodyActivityContext,
    BodyAttentionIntent as FacadeBodyAttentionIntent,
    BodyExpressionRequest as FacadeBodyExpressionRequest,
    EmbodiedExpressionIntent as FacadeEmbodiedExpressionIntent,
    SpeechPresentationRequest as FacadeSpeechPresentationRequest,
)
from app.domain.body_activity_context import (
    BodyActivityContext,
    BodyPostureTendency,
)
from app.domain.body_attention_intent import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)
from app.domain.body_expression import EmbodiedExpressionIntent
from app.domain.body_expression_input import BodyExpressionInput
from app.domain.body_expression_request import BodyExpressionRequest
from app.domain.body_speech import SpeechPresentationRequest
from app.domain.emotions.emotion_state import (
    EmotionState,
    MoodType,
    ReactiveEmotionState,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.body_affect_baseline_projector import (
    BodyAffectBaselineProjector,
)
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.body_facial_affect_resolver import BodyFacialAffectResolver

pytestmark = pytest.mark.unit


def _intention(kind: InteractionIntentionType) -> InteractionIntention:
    return InteractionIntention(
        intention=kind,
        confidence=0.9,
        source="test",
        reason="body_affect_test",
        target_type="counterpart",
        target_id="user",
        observation_only=False,
    )


def _context(
    *,
    intention: InteractionIntention | None = None,
    attention_target: str | None = "conversation_partner",
    posture: BodyPostureTendency = BodyPostureTendency.OPEN,
) -> BodyActivityContext:
    return BodyActivityContext(
        source_activity_id="activity-1",
        attention_target=attention_target,
        engagement=0.76,
        posture_tendency=posture,
        movement_energy=0.38,
        gaze_freedom=0.24,
        interaction_intention=intention,
    )


def test_joy_projects_to_positive_body_affect_without_pose() -> None:
    baseline = BodyAffectBaselineProjector().project(
        EmotionState(
            mood=MoodType.HAPPY,
            arousal=0.72,
            valence=0.64,
            talkativeness=0.70,
            reactive=ReactiveEmotionState(joy=0.82, amusement=0.44),
        )
    )

    assert baseline.dominant_affect == "joy"
    assert baseline.valence > 0.5
    assert baseline.warmth > 0.65
    assert baseline.approach > 0.2
    assert baseline.expressiveness > 0.6
    assert "joint" not in baseline.as_payload()
    assert "motion" not in baseline.as_payload()


def test_fear_projects_to_tension_and_avoidance_not_motion_command() -> None:
    baseline = BodyAffectBaselineProjector().project(
        EmotionState(
            mood=MoodType.NEUTRAL,
            arousal=0.82,
            valence=-0.52,
            talkativeness=0.30,
            reactive=ReactiveEmotionState(
                fear=0.90,
                discomfort=0.52,
                emotional_pressure=0.44,
            ),
        )
    )

    assert baseline.dominant_affect == "fear"
    assert baseline.tension > 0.75
    assert baseline.avoidance >= 0.9
    assert baseline.approach < -0.4
    assert "gesture" not in baseline.as_payload()


def test_facial_affect_resolver_keeps_emotion_baseline_under_overlay() -> None:
    projector = BodyAffectBaselineProjector()
    resolver = BodyFacialAffectResolver()
    baseline = projector.project(
        EmotionState(
            mood=MoodType.SAD,
            arousal=0.30,
            valence=-0.60,
            reactive=ReactiveEmotionState(sadness=0.82),
        )
    )
    gentle_overlay = EmbodiedExpressionIntent(
        attitude="gentle",
        intensity=0.40,
        valence=0.10,
        arousal=0.22,
        tension=0.12,
        openness=0.70,
        approach=0.24,
        warmth=0.92,
    )

    target = resolver.resolve(baseline, gentle_overlay)

    assert target.frown > target.smile
    assert target.frown > 0.45
    assert target.smile > 0.0


def test_body_expression_input_keeps_affect_and_interaction_as_separate_layers() -> None:
    result = BodyExpressionInputBuilder().build(
        emotion=EmotionState(
            mood=MoodType.SAD,
            arousal=0.34,
            valence=-0.48,
            reactive=ReactiveEmotionState(sadness=0.74),
        ),
        context=_context(
            intention=_intention(InteractionIntentionType.COMFORT),
            attention_target="trusted_user",
            posture=BodyPostureTendency.FORWARD,
        ),
    )

    assert isinstance(result, BodyExpressionInput)
    assert result.affect_baseline.dominant_affect == "sadness"
    assert result.expression_overlay is not None
    assert result.expression_overlay.attitude == "gentle"
    assert result.activity_context.posture_tendency is BodyPostureTendency.FORWARD
    assert result.attention_intent is not None
    assert result.attention_intent.target == "trusted_user"
    assert result.attention_intent.behavior is BodyAttentionBehavior.MAINTAIN


def test_body_expression_input_exists_without_interaction_intention() -> None:
    result = BodyExpressionInputBuilder().build(
        emotion=EmotionState(
            mood=MoodType.EXCITED,
            arousal=0.80,
            valence=0.24,
            talkativeness=0.72,
            reactive=ReactiveEmotionState(surprise=0.62),
        ),
        context=_context(intention=None, attention_target=None),
    )

    assert result.expression_overlay is None
    assert result.attention_intent is None
    assert result.affect_baseline.surprise == 0.62
    assert result.facial_target.eye_widen > 0.4


def test_boundary_intention_increases_attention_avoidance_without_authority() -> None:
    result = BodyExpressionInputBuilder().build(
        emotion=EmotionState(
            mood=MoodType.NEUTRAL,
            arousal=0.62,
            valence=-0.22,
            reactive=ReactiveEmotionState(discomfort=0.68),
        ),
        context=_context(
            intention=_intention(InteractionIntentionType.SET_BOUNDARY),
        ),
    )

    assert result.attention_intent is not None
    assert result.attention_intent.behavior is BodyAttentionBehavior.AVOID
    assert result.attention_intent.avoidance >= 0.72
    payload = result.as_payload()
    assert payload["grants_execution_authority"] is False
    assert payload["contains_pose"] is False
    assert "joints" not in payload
    assert "motion" not in payload


def test_body_high_level_facade_reexports_split_contracts() -> None:
    assert FacadeBodyActivityContext is BodyActivityContext
    assert FacadeBodyAttentionIntent is BodyAttentionIntent
    assert FacadeBodyExpressionRequest is BodyExpressionRequest
    assert FacadeEmbodiedExpressionIntent is EmbodiedExpressionIntent
    assert FacadeSpeechPresentationRequest is SpeechPresentationRequest


def test_affect_projector_rejects_non_finite_emotion_values() -> None:
    emotion = EmotionState(arousal=float("nan"))

    with pytest.raises(ValueError, match="arousal must be finite"):
        BodyAffectBaselineProjector().project(emotion)
