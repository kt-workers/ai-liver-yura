from __future__ import annotations

from app.domain.appraisal import StateFacetKind

from .contracts import (
    CharacterVoiceStyleInfluenceRule,
    ExpressionAxis,
    ExpressionPerformanceRule,
    LinguisticPerformancePolicy,
    PerformanceAxis,
    PerformanceIntentDelta,
    SpeechPerformanceProjectionPolicy,
    SpeechStateInfluenceRule,
    StateComponent,
    StateTargetScope,
    StateTransform,
)

SUBTLE = 0.15
MILD = 0.30
MODERATE = 0.50


def _delta(*values: tuple[PerformanceAxis, float]) -> PerformanceIntentDelta:
    return PerformanceIntentDelta(values)


def yura_revision_1_policy() -> SpeechPerformanceProjectionPolicy:
    return SpeechPerformanceProjectionPolicy(
        "yura-speech-performance",
        1,
        (
            CharacterVoiceStyleInfluenceRule(
                "yura-baseline-softness",
                "yura",
                "baseline_softness",
                "柔らかく親しみがある",
                _delta((PerformanceAxis.SOFTNESS, MODERATE), (PerformanceAxis.TENSION, -MILD)),
            ),
            CharacterVoiceStyleInfluenceRule(
                "yura-calmness",
                "yura",
                "calmness_tendency",
                "比較的落ち着いた基調",
                _delta(
                    (PerformanceAxis.PACE, -SUBTLE),
                    (PerformanceAxis.ENERGY, -SUBTLE),
                    (PerformanceAxis.TENSION, -MILD),
                    (PerformanceAxis.PITCH_RANGE, -SUBTLE),
                ),
            ),
            CharacterVoiceStyleInfluenceRule(
                "yura-expressive",
                "yura",
                "emotional_expressiveness_tendency",
                "EmotionやSituationに応じて相対的に変化し、喜びや驚きが強い時は普段より素直に表出が増え得る",
                _delta(),
                ((ExpressionAxis.EXPRESSIVENESS, 1.15), (ExpressionAxis.ENERGY, 1.10)),
            ),
            CharacterVoiceStyleInfluenceRule(
                "yura-energy",
                "yura",
                "energy_tendency",
                "常時高energyで押さず、現在のEmotionやSituationに応じて自然に変化する",
                _delta(),
                ((ExpressionAxis.ENERGY, 1.0),),
            ),
        ),
        (
            SpeechStateInfluenceRule(
                "energy-current",
                StateFacetKind.ENERGY,
                None,
                StateTargetScope.GLOBAL,
                StateComponent.CURRENT,
                StateTransform.SIGNED,
                (
                    (ExpressionAxis.ENERGY, MODERATE),
                    (ExpressionAxis.PACING_BIAS, MILD),
                    (ExpressionAxis.EXPRESSIVENESS, SUBTLE),
                ),
            ),
            SpeechStateInfluenceRule(
                "arousal-current",
                StateFacetKind.AROUSAL,
                None,
                StateTargetScope.GLOBAL,
                StateComponent.CURRENT,
                StateTransform.SIGNED,
                (
                    (ExpressionAxis.ACTIVATION, MODERATE),
                    (ExpressionAxis.ENERGY, MILD),
                    (ExpressionAxis.PACING_BIAS, MILD),
                    (ExpressionAxis.TENSION, MILD),
                    (ExpressionAxis.EXPRESSIVENESS, MILD),
                ),
            ),
        ),
        (
            ExpressionPerformanceRule(
                ExpressionAxis.ACTIVATION,
                _delta(
                    (PerformanceAxis.ENERGY, MODERATE),
                    (PerformanceAxis.PITCH_RANGE, MILD),
                    (PerformanceAxis.PACE, MILD),
                ),
            ),
            ExpressionPerformanceRule(
                ExpressionAxis.ENERGY,
                _delta(
                    (PerformanceAxis.ENERGY, MODERATE),
                    (PerformanceAxis.LOUDNESS, SUBTLE),
                    (PerformanceAxis.PACE, SUBTLE),
                ),
            ),
            ExpressionPerformanceRule(
                ExpressionAxis.SOFTNESS,
                _delta((PerformanceAxis.SOFTNESS, MODERATE), (PerformanceAxis.TENSION, -SUBTLE)),
            ),
            ExpressionPerformanceRule(
                ExpressionAxis.WARMTH,
                _delta(
                    (PerformanceAxis.SOFTNESS, SUBTLE), (PerformanceAxis.EXPRESSIVENESS, SUBTLE)
                ),
            ),
            ExpressionPerformanceRule(
                ExpressionAxis.TENSION,
                _delta((PerformanceAxis.TENSION, MODERATE), (PerformanceAxis.SOFTNESS, -SUBTLE)),
            ),
            ExpressionPerformanceRule(
                ExpressionAxis.EXPRESSIVENESS,
                _delta(
                    (PerformanceAxis.EXPRESSIVENESS, MODERATE),
                    (PerformanceAxis.PITCH_RANGE, SUBTLE),
                ),
            ),
            ExpressionPerformanceRule(
                ExpressionAxis.PACING_BIAS, _delta((PerformanceAxis.PACE, MODERATE))
            ),
        ),
        LinguisticPerformancePolicy(0.2, 0.5, 0.8, 0.8, 0.2, 0.5),
    )
