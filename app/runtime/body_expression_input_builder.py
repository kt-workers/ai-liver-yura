from __future__ import annotations

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_awakening_affect import BodyAwakeningAffect
from app.domain.body_expression_input import BodyExpressionInput
from app.domain.body_expression_request import BodyExpressionRequest
from app.domain.emotions.emotion_state import EmotionState
from app.runtime.body_affect_baseline_projector import (
    BodyAffectBaselineProjector,
)
from app.runtime.body_attention_intent_resolver import BodyAttentionIntentResolver
from app.runtime.body_awakening_affect_modulator import BodyAwakeningAffectModulator
from app.runtime.body_awakening_facial_modulator import BodyAwakeningFacialModulator
from app.runtime.body_facial_affect_resolver import BodyFacialAffectResolver
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjection,
    InteractionExpressionProjector,
)


class BodyExpressionInputBuilder:
    """Emotion・覚醒・Interaction・一時表現要求をPose前入力へ束ねる。"""

    def __init__(
        self,
        *,
        affect_projector: BodyAffectBaselineProjector | None = None,
        awakening_affect_modulator: BodyAwakeningAffectModulator | None = None,
        awakening_facial_modulator: BodyAwakeningFacialModulator | None = None,
        interaction_projector: InteractionExpressionProjector | None = None,
        facial_resolver: BodyFacialAffectResolver | None = None,
        attention_resolver: BodyAttentionIntentResolver | None = None,
    ) -> None:
        self._affect_projector = affect_projector or BodyAffectBaselineProjector()
        self._awakening_affect_modulator = (
            awakening_affect_modulator or BodyAwakeningAffectModulator()
        )
        self._awakening_facial_modulator = (
            awakening_facial_modulator or BodyAwakeningFacialModulator()
        )
        self._interaction_projector = (
            interaction_projector or InteractionExpressionProjector()
        )
        self._facial_resolver = facial_resolver or BodyFacialAffectResolver()
        self._attention_resolver = attention_resolver or BodyAttentionIntentResolver()

    def build(
        self,
        *,
        emotion: EmotionState,
        context: BodyActivityContext,
        expression_request: BodyExpressionRequest | None = None,
        awakening_affect: BodyAwakeningAffect | None = None,
    ) -> BodyExpressionInput:
        if not isinstance(context, BodyActivityContext):
            raise TypeError("context must be BodyActivityContext")
        if expression_request is not None and not isinstance(
            expression_request,
            BodyExpressionRequest,
        ):
            raise TypeError("expression_request must be BodyExpressionRequest")
        if awakening_affect is not None and not isinstance(
            awakening_affect,
            BodyAwakeningAffect,
        ):
            raise TypeError("awakening_affect must be BodyAwakeningAffect")

        baseline = self._affect_projector.project(emotion)
        baseline = self._awakening_affect_modulator.modulate(
            baseline,
            awakening_affect,
        )
        projection = self._project_interaction(context)
        overlay = (
            expression_request.expression
            if expression_request is not None
            else (
                projection.embodied_expression
                if projection is not None
                else None
            )
        )
        preferred_attention = (
            expression_request.attention
            if expression_request is not None
            and expression_request.attention is not None
            else (
                projection.attention_intent
                if projection is not None
                else None
            )
        )
        facial_target = self._facial_resolver.resolve(baseline, overlay)
        facial_target = self._awakening_facial_modulator.modulate(
            facial_target,
            awakening_affect,
        )
        attention = self._attention_resolver.resolve(
            context=context,
            baseline=baseline,
            preferred_attention=preferred_attention,
        )
        return BodyExpressionInput(
            activity_context=context,
            affect_baseline=baseline,
            facial_target=facial_target,
            expression_overlay=overlay,
            attention_intent=attention,
            awakening_affect=awakening_affect,
        )

    def _project_interaction(
        self,
        context: BodyActivityContext,
    ) -> InteractionExpressionProjection | None:
        intention = context.interaction_intention
        if intention is None:
            return None
        return self._interaction_projector.project(intention)
