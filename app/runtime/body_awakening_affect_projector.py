from __future__ import annotations

from app.domain.awakening_state import AwakeningLifecyclePhase, AwakeningState
from app.domain.body_awakening_affect import BodyAwakeningAffect


class BodyAwakeningAffectProjector:
    """覚醒状態をBody表現傾向へ射影する。Pose・Motion名は決定しない。"""

    def project(self, state: AwakeningState | None) -> BodyAwakeningAffect:
        if state is None:
            return BodyAwakeningAffect()
        if not isinstance(state, AwakeningState):
            raise TypeError("state must be AwakeningState or None")

        appraisal = state.appraisal
        salience = {
            AwakeningLifecyclePhase.INITIALIZING: 1.0,
            AwakeningLifecyclePhase.WAKING: 1.0,
            AwakeningLifecyclePhase.ORIENTING: 0.72,
            AwakeningLifecyclePhase.READY: 0.0,
        }[state.phase]
        return BodyAwakeningAffect(
            activation=appraisal.activation_urge,
            drowsiness=appraisal.sleepiness,
            orientation=appraisal.orientation_need,
            security=appraisal.security_need,
            exploration=appraisal.exploration_urge,
            social=appraisal.social_urge,
            readiness=appraisal.readiness,
            salience=salience,
        )


__all__ = ["BodyAwakeningAffectProjector"]
