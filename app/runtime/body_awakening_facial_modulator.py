from __future__ import annotations

from app.domain.body_affect import BodyFacialAffectTarget
from app.domain.body_awakening_affect import BodyAwakeningAffect


class BodyAwakeningFacialModulator:
    """覚醒傾向を既存Face targetへ合成する。固定表情Presetは生成しない。"""

    def modulate(
        self,
        target: BodyFacialAffectTarget,
        awakening: BodyAwakeningAffect | None,
    ) -> BodyFacialAffectTarget:
        if not isinstance(target, BodyFacialAffectTarget):
            raise TypeError("target must be BodyFacialAffectTarget")
        if awakening is None or not awakening.active:
            return target
        if not isinstance(awakening, BodyAwakeningAffect):
            raise TypeError("awakening must be BodyAwakeningAffect")

        weight = awakening.salience
        return BodyFacialAffectTarget(
            smile=target.smile,
            frown=target.frown,
            brow_raise=self._unit(
                target.brow_raise
                + weight * awakening.orientation * awakening.activation * 0.16
            ),
            brow_tension=self._unit(
                target.brow_tension + weight * awakening.security * 0.18
            ),
            eye_widen=self._unit(
                target.eye_widen
                + weight
                * (
                    awakening.activation * 0.16
                    + awakening.orientation * 0.12
                    - awakening.drowsiness * 0.10
                )
            ),
            eye_narrow=self._unit(
                target.eye_narrow
                + weight
                * (
                    awakening.drowsiness * 0.30
                    + awakening.security * 0.06
                    - awakening.activation * 0.08
                )
            ),
            mouth_tension=self._unit(
                target.mouth_tension + weight * awakening.security * 0.10
            ),
        )

    @staticmethod
    def _unit(value: float) -> float:
        return max(0.0, min(1.0, float(value)))


__all__ = ["BodyAwakeningFacialModulator"]
