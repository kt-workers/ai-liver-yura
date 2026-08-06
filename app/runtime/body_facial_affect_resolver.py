from __future__ import annotations

from app.domain.body_affect import BodyAffectBaseline, BodyFacialAffectTarget
from app.domain.body_expression import EmbodiedExpressionIntent


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class BodyFacialAffectResolver:
    """感情基礎表現と対人的Overlayからモデル非依存な顔表現を解決する。"""

    def resolve(
        self,
        baseline: BodyAffectBaseline,
        overlay: EmbodiedExpressionIntent | None = None,
    ) -> BodyFacialAffectTarget:
        if not isinstance(baseline, BodyAffectBaseline):
            raise TypeError("baseline must be BodyAffectBaseline")
        if overlay is not None and not isinstance(
            overlay,
            EmbodiedExpressionIntent,
        ):
            raise TypeError("overlay must be EmbodiedExpressionIntent")

        channels = baseline.channels
        overlay_intensity = overlay.intensity if overlay is not None else 0.0
        overlay_positive = (
            max(0.0, overlay.valence) * overlay_intensity
            if overlay is not None
            else 0.0
        )
        overlay_negative = (
            max(0.0, -overlay.valence) * overlay_intensity
            if overlay is not None
            else 0.0
        )
        overlay_warmth = (
            overlay.warmth * overlay_intensity
            if overlay is not None
            else 0.0
        )
        overlay_tension = (
            overlay.tension * overlay_intensity
            if overlay is not None
            else 0.0
        )
        overlay_surprise = (
            overlay.surprise * overlay_intensity
            if overlay is not None
            else 0.0
        )
        overlay_assertiveness = (
            overlay.assertiveness * overlay_intensity
            if overlay is not None
            else 0.0
        )
        overlay_openness = overlay.openness if overlay is not None else 0.5

        smile = _clamp(
            channels.joy * 0.48
            + channels.amusement * 0.42
            + max(0.0, baseline.valence) * 0.18
            + overlay_positive * 0.28
            + overlay_warmth * 0.10
        )
        frown = _clamp(
            channels.sadness * 0.48
            + channels.anger * 0.32
            + channels.discomfort * 0.30
            + max(0.0, -baseline.valence) * 0.20
            + overlay_negative * 0.26
        )
        brow_raise = _clamp(
            max(channels.surprise, baseline.surprise) * 0.82
            + overlay_surprise * 0.38
        )
        brow_tension = _clamp(
            baseline.tension * 0.52
            + channels.anger * 0.36
            + channels.fear * 0.28
            + channels.discomfort * 0.24
            + overlay_tension * 0.30
        )
        eye_widen = _clamp(
            channels.surprise * 0.72
            + channels.fear * 0.42
            + overlay_surprise * 0.36
        )
        eye_narrow = _clamp(
            channels.anger * 0.54
            + channels.discomfort * 0.28
            + overlay_assertiveness * 0.34
        )
        mouth_tension = _clamp(
            baseline.tension * 0.44
            + channels.discomfort * 0.38
            + channels.anger * 0.28
            + overlay_tension * 0.28
            + max(0.0, 0.5 - overlay_openness) * overlay_intensity * 0.20
        )

        return BodyFacialAffectTarget(
            smile=smile,
            frown=frown,
            brow_raise=brow_raise,
            brow_tension=brow_tension,
            eye_widen=eye_widen,
            eye_narrow=eye_narrow,
            mouth_tension=mouth_tension,
        )
