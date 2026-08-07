from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_affect import BodyAffectBaseline, BodyFacialAffectTarget
from app.domain.body_attention_intent import BodyAttentionIntent
from app.domain.body_awakening_affect import BodyAwakeningAffect
from app.domain.body_expression import EmbodiedExpressionIntent


@dataclass(frozen=True, slots=True)
class BodyExpressionInput:
    """連続Pose Controllerへ渡す、Pose計算前の高レベル入力。

    感情基礎表現と対人的な一時表現、覚醒由来の連続傾向を別レイヤーで保持する。
    """

    activity_context: BodyActivityContext
    affect_baseline: BodyAffectBaseline
    facial_target: BodyFacialAffectTarget
    expression_overlay: EmbodiedExpressionIntent | None = None
    attention_intent: BodyAttentionIntent | None = None
    awakening_affect: BodyAwakeningAffect | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.activity_context, BodyActivityContext):
            raise TypeError("activity_context must be BodyActivityContext")
        if not isinstance(self.affect_baseline, BodyAffectBaseline):
            raise TypeError("affect_baseline must be BodyAffectBaseline")
        if not isinstance(self.facial_target, BodyFacialAffectTarget):
            raise TypeError("facial_target must be BodyFacialAffectTarget")
        if self.expression_overlay is not None and not isinstance(
            self.expression_overlay,
            EmbodiedExpressionIntent,
        ):
            raise TypeError(
                "expression_overlay must be EmbodiedExpressionIntent"
            )
        if self.attention_intent is not None and not isinstance(
            self.attention_intent,
            BodyAttentionIntent,
        ):
            raise TypeError("attention_intent must be BodyAttentionIntent")
        if self.awakening_affect is not None and not isinstance(
            self.awakening_affect,
            BodyAwakeningAffect,
        ):
            raise TypeError("awakening_affect must be BodyAwakeningAffect")

    @property
    def source_activity_id(self) -> str:
        return self.activity_context.source_activity_id

    def as_payload(self) -> dict[str, object]:
        return {
            "source_activity_id": self.source_activity_id,
            "affect_baseline": self.affect_baseline.as_payload(),
            "facial_target": self.facial_target.as_payload(),
            "expression_overlay": (
                self.expression_overlay.as_payload()
                if self.expression_overlay is not None
                else None
            ),
            "attention_intent": (
                self.attention_intent.as_payload()
                if self.attention_intent is not None
                else None
            ),
            "awakening_affect": (
                self.awakening_affect.as_payload()
                if self.awakening_affect is not None
                else None
            ),
            "activity_context": {
                "attention_target": self.activity_context.attention_target,
                "engagement": self.activity_context.engagement,
                "posture_tendency": (
                    self.activity_context.posture_tendency.value
                ),
                "movement_energy": self.activity_context.movement_energy,
                "gaze_freedom": self.activity_context.gaze_freedom,
            },
            "grants_execution_authority": False,
            "contains_pose": False,
        }
