from __future__ import annotations

from app.domain.body_affect import BodyAffectBaseline
from app.domain.body_awakening_affect import BodyAwakeningAffect


class BodyAwakeningAffectModulator:
    """既存Emotion由来Baselineへ覚醒傾向を連続合成する。

    Emotion channel自体、dominant affect、Pose、Motion名は変更しない。
    """

    def modulate(
        self,
        baseline: BodyAffectBaseline,
        awakening: BodyAwakeningAffect | None,
    ) -> BodyAffectBaseline:
        if not isinstance(baseline, BodyAffectBaseline):
            raise TypeError("baseline must be BodyAffectBaseline")
        if awakening is None or not awakening.active:
            return baseline
        if not isinstance(awakening, BodyAwakeningAffect):
            raise TypeError("awakening must be BodyAwakeningAffect")

        weight = awakening.salience
        activation_delta = awakening.activation - awakening.drowsiness
        social_opening = awakening.social * 0.22 + awakening.exploration * 0.16
        guardedness = awakening.security * 0.24 + awakening.drowsiness * 0.08

        return BodyAffectBaseline(
            channels=baseline.channels,
            dominant_affect=baseline.dominant_affect,
            intensity=self._unit(
                baseline.intensity
                + weight * (
                    awakening.activation * 0.10
                    + awakening.orientation * 0.05
                    - awakening.drowsiness * 0.06
                )
            ),
            valence=self._signed(baseline.valence),
            arousal=self._unit(
                baseline.arousal + weight * activation_delta * 0.30
            ),
            tension=self._unit(
                baseline.tension
                + weight * (
                    awakening.security * 0.22
                    + awakening.orientation * 0.06
                )
            ),
            openness=self._unit(
                baseline.openness + weight * (social_opening - guardedness)
            ),
            approach=self._signed(
                baseline.approach
                + weight
                * (
                    awakening.activation * 0.10
                    + awakening.social * 0.14
                    - awakening.security * 0.20
                    - awakening.drowsiness * 0.08
                )
            ),
            warmth=self._unit(
                baseline.warmth
                + weight * (awakening.social * 0.08 - awakening.security * 0.06)
            ),
            surprise=baseline.surprise,
            assertiveness=self._unit(
                baseline.assertiveness
                + weight
                * (
                    awakening.activation * 0.12
                    - awakening.drowsiness * 0.08
                    - awakening.security * 0.05
                )
            ),
            expressiveness=self._unit(
                baseline.expressiveness
                + weight
                * (
                    awakening.activation * 0.18
                    + awakening.social * 0.12
                    - awakening.drowsiness * 0.22
                    - awakening.security * 0.08
                )
            ),
            avoidance=self._unit(
                baseline.avoidance
                + weight
                * (
                    awakening.security * 0.20
                    + awakening.drowsiness * 0.04
                )
            ),
        )

    @staticmethod
    def _unit(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _signed(value: float) -> float:
        return max(-1.0, min(1.0, float(value)))


__all__ = ["BodyAwakeningAffectModulator"]
