from __future__ import annotations

from app.domain.body_expression_input import BodyExpressionInput
from app.domain.body_motion_state import BodyInnerMotionState


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class BodyMotionStateProjector:
    """高レベルBody表現入力を連続運動用Snapshotへ射影する。"""

    def project(self, value: BodyExpressionInput) -> BodyInnerMotionState:
        if not isinstance(value, BodyExpressionInput):
            raise TypeError("value must be BodyExpressionInput")

        baseline = value.affect_baseline
        context = value.activity_context
        overlay = value.expression_overlay
        attention = value.attention_intent

        overlay_arousal = overlay.arousal if overlay is not None else 0.0
        overlay_tension = overlay.tension if overlay is not None else 0.0
        overlay_openness = overlay.openness if overlay is not None else 0.5
        overlay_assertiveness = overlay.assertiveness if overlay is not None else 0.0
        attention_avoidance = attention.avoidance if attention is not None else 0.0

        return BodyInnerMotionState(
            arousal=_clamp(baseline.arousal * 0.78 + overlay_arousal * 0.22),
            tension=_clamp(baseline.tension * 0.82 + overlay_tension * 0.18),
            curiosity=_clamp(
                context.gaze_freedom * 0.72
                + baseline.surprise * 0.16
                + (0.12 if overlay is not None and overlay.attitude == "curious" else 0.0)
            ),
            confidence=_clamp(
                baseline.assertiveness * 0.48
                + baseline.openness * 0.30
                + overlay_assertiveness * 0.14
                + overlay_openness * 0.08
            ),
            engagement=_clamp(
                context.engagement * 0.72
                + baseline.expressiveness * 0.18
                + (attention.engagement * 0.10 if attention is not None else 0.0)
            ),
            avoidance=_clamp(
                max(
                    baseline.avoidance,
                    attention_avoidance,
                )
            ),
            movement_energy=_clamp(
                context.movement_energy * 0.62
                + baseline.expressiveness * 0.22
                + baseline.arousal * 0.16
            ),
        )
